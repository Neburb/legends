"""Host output gates plus CI execution of an adversarial source in Docker."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import isolated_release as isolated
import test_package_release as packaging
PACKAGER, VERSION = packaging.PACKAGER, packaging.VERSION
from test_archive_limits import fixture


class HostGates(unittest.TestCase):
    def execute(self, data, out, downloaded=None, timeout=False, code=0):
        captured=[]
        class Process:
            stdout=io.BytesIO(data);returncode=None
            def poll(self):return self.returncode
            def wait(self, **options):
                if self.returncode is None:self.returncode=code
                return self.returncode
            def kill(self):self.returncode=-9
        process=Process()
        def popen(args, **options):captured.append((args,options));return process
        class Timer:
            def __init__(self, seconds, callback):self.callback=callback
            def start(self):
                if timeout:self.callback()
            def cancel(self):pass
            def join(self):pass
        with patch.object(isolated.subprocess,'Popen',side_effect=popen),patch.object(isolated.subprocess,'run') as drain,patch.object(isolated.threading,'Timer',Timer):
            try:isolated.isolated_build('.', 'a'*40,VERSION,out,downloaded)
            finally:
                args,options=captured[0];self.assertEqual(drain.call_args.args[0],['docker','rm','--force',args[args.index('--name')+1]])
                self.assertTrue(process.stdout.closed)
        return args, options

    def test_container_has_only_required_mounts_and_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'PUBLIC_TOKEN':'parent-secret','INPUT_GITHUB_TOKEN':'private-secret'}):
            args,options=self.execute(fixture(),Path(directory)/'published',fixture())
            self.assertFalse((Path(directory)/'published').exists())
        for flag in ('--network=none','--read-only','--user=65534:65534','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=64','--memory=1g','--tmpfs=/out:rw,nosuid,noexec,size=256m,mode=1777','--log-driver=none'):
            self.assertIn(flag,args)
        self.assertNotIn('--pid=host',args);self.assertNotIn('--privileged',args)
        self.assertEqual(sum(a=='--mount' for a in args),2)
        self.assertTrue(all('readonly' in args[i+1] for i,a in enumerate(args) if a=='--mount'))
        self.assertNotIn('PUBLIC_TOKEN',options['env']);self.assertNotIn('INPUT_GITHUB_TOKEN',options['env'])

    def test_timeout_drains_container_before_propagating_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.TimeoutExpired):self.execute(fixture(),Path(directory)/'dist',timeout=True)
            self.assertFalse((Path(directory)/'dist').exists())

    def test_bad_download_never_executes_source(self):
        with patch.object(isolated.subprocess,'Popen',side_effect=AssertionError('source executed')):
            with self.assertRaises(ValueError):isolated.isolated_build('.', 'a'*40,VERSION,'dist',b'bad')

    def test_host_rejects_source_output_even_if_container_returns_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'unsafe'):self.execute(fixture({'config/.npmrc':b'secret'}),Path(directory)/'dist')
            self.assertFalse((Path(directory)/'dist').exists())

    def test_pipe_output_is_bounded_and_container_is_drained(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(isolated,'MAX_ARCHIVE',1024):
            with self.assertRaisesRegex(ValueError,'size limit'):self.execute(b'x'*1025,Path(directory)/'dist')
            self.assertFalse((Path(directory)/'dist').exists())

    def test_container_failure_never_publishes_output(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError):self.execute(fixture(),Path(directory)/'dist',code=1)
            self.assertFalse((Path(directory)/'dist').exists())

    def test_recovery_and_source_proof_use_only_isolated_entry(self):
        root=Path(__file__).resolve().parents[1];doc=(root/'docs/release-recovery.md').read_text()
        self.assertNotIn('python3 "$RECIPE_DIR/scripts/package_release.py"',doc)
        self.assertIn('docker build -t legends-release-builder -f "$RECIPE_DIR/scripts/release-container.Dockerfile" "$RECIPE_DIR/scripts"',doc)
        self.assertIn('python3 "$RECIPE_DIR/scripts/isolated_release.py"',doc)
        self.assertFalse((root/'scripts/verify_release_source.py').exists())


@unittest.skipUnless(os.environ.get('RUN_CONTAINER_TESTS')=='1','Docker integration runs in Linux CI')
class ContainerIntegration(packaging.Packaging):
    # Inherited recipe tests are also executed in the Linux runtime.
    def test_real_container_blocks_parent_credentials_workspace_and_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,sha=self.fixture(root)
            sentinel=root/'parent-secret.txt';sentinel.write_text('parent-secret')
            probes="""import os,json,pathlib,socket,subprocess
checks={}
checks['uid']=os.getuid()==65534
# Writes must hit tmpfs ENOSPC, without consuming the runner filesystem.
import errno
v=os.statvfs('/out');checks['output_quota']=v.f_blocks*v.f_frsize<=256*1024*1024
try:
 with open('/out/fill','wb',buffering=0) as f:
  for i in range(18):f.write(b'x'*(16*1024*1024))
 checks['output_enospc']=False
except OSError as e:checks['output_enospc']=e.errno==errno.ENOSPC
finally:pathlib.Path('/out/fill').unlink(missing_ok=True)

checks['env']=not any('secret' in v for v in os.environ.values())
try: checks['parent_env']=b'parent-secret' not in pathlib.Path('/proc/1/environ').read_bytes()
except PermissionError: checks['parent_env']=True
try: pathlib.Path(SENTINEL).read_bytes();checks['workspace']=False
except OSError: checks['workspace']=True
for target in ('/source/attack.txt','/recipe/attack.txt'):
 try: pathlib.Path(target).write_text('attack');checks[target]=False
 except OSError:checks[target]=True
try:
 s=socket.create_connection(('1.1.1.1',443),timeout=1);s.close();checks['network']=False
except OSError:checks['network']=True
checks['capabilities']='CapEff:\t0000000000000000' in pathlib.Path('/proc/self/status').read_text()
# An outstanding source descendant must not survive container exit.
subprocess.Popen(['python3','-c','import time;time.sleep(60)'])
pathlib.Path('isolation-probes.json').write_text(json.dumps(checks))
""".replace('SENTINEL',repr(str(sentinel)))
            (source/'tools/package.py').write_text(probes+PACKAGER,encoding='utf-8',newline='\n')
            self.git(source,'add','tools/package.py');self.git(source,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','adversarial source')
            sha=self.git(source,'rev-parse','HEAD')
            with patch.dict(os.environ,{'PUBLIC_TOKEN':'parent-secret','INPUT_GITHUB_TOKEN':'private-secret'}):
                isolated.isolated_build(source,sha,VERSION,root/'dist')
            with zipfile.ZipFile(root/'dist'/('stadium_realtime_combat-'+VERSION+'.zip')) as z:
                checks=json.loads(z.read('isolation-probes.json'))
            self.assertTrue(all(checks.values()),checks)
            self.assertEqual(sentinel.read_text(),'parent-secret')
            remaining=subprocess.check_output(['docker','ps','-a','--filter','name=legends-package-','--format','{{.Names}}'],text=True).strip()
            self.assertEqual(remaining,'')

    def test_real_isolated_build_and_retry_equal_the_source_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source,sha=self.fixture(root)
            isolated.isolated_build(source,sha,VERSION,root/'dist')
            data=(root/'dist'/('stadium_realtime_combat-'+VERSION+'.zip')).read_bytes()
            isolated.isolated_build(source,sha,VERSION,root/'ignored',data)
            self.assertFalse((root/'ignored').exists())


if __name__=='__main__':unittest.main()
