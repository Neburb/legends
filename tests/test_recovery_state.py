import importlib.util
import subprocess
import pathlib
import unittest
spec=importlib.util.spec_from_file_location('inspect_release',pathlib.Path(__file__).parents[1]/'scripts/inspect_recovery_release.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RecoveryState(unittest.TestCase):
    def stub(self, code=0, status=200, body='{"draft":true}', repo_error=False):
        def run(args, **kw):
            if '--include' not in args:
                if repo_error: raise subprocess.CalledProcessError(1,args)
                return subprocess.CompletedProcess(args,0,'{}','')
            return subprocess.CompletedProcess(args,code,f'HTTP/2.0 {status} message\nContent-Type: application/json\n\n{body}', 'API failure' if code else '')
        return run
    def test_existing(self): self.assertTrue(m.inspect('v0.0.75',self.stub())['draft'])
    def test_orphan(self): self.assertIsNone(m.inspect('v0.0.75',self.stub(1,404)))
    def test_api_failures(self):
        for status in [401,403,429,500]:
            with self.subTest(status=status),self.assertRaises(RuntimeError):m.inspect('v0.0.75',self.stub(1,status))
    def test_repo_access_failure(self):
        with self.assertRaises(subprocess.CalledProcessError):m.inspect('v0.0.75',self.stub(1,404,repo_error=True))
    def test_network_failure(self):
        def run(args,**kw):return subprocess.CompletedProcess(args,1,'','network error') if '--include' in args else subprocess.CompletedProcess(args,0,'{}','')
        with self.assertRaises(RuntimeError):m.inspect('v0.0.75',run)
if __name__=='__main__':unittest.main()
