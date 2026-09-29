const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/publish.yml'), 'utf8').replaceAll('\r\n', '\n');
const guard = workflow.match(/        id: boundary[\s\S]*?          script: \|\n([\s\S]*?)\n      - name: Publish GitHub Release/)[1].split('\n').map(line => line.slice(12)).join('\n');
assert.match(workflow, /if: steps\.boundary\.outputs\.allowed == 'true'/);
const run = new (Object.getPrototypeOf(async function() {}).constructor)('github', 'core', 'require', guard);
const sha = 'a'.repeat(40), newer = 'b'.repeat(40);
const zipName = 'stadium_realtime_combat-0.0.75.zip';
function makeZip({manifestVersion='0.0.75',mainVersion='0.0.75',githubRepo='Neburb/legends',missingManifest=false,duplicate=false,badInternal=false,missingInternal=false,extra={},symlink=false}={}) {
  const files={'manifest.json':JSON.stringify({id:'stadium_realtime_combat',entry:'main.lua',version:manifestVersion,github:githubRepo}),
    'main.lua':`return function(mod) mod.exports.version="${mainVersion}" end`,'fixture.txt':'crc fixture payload',...extra};
  if(!missingInternal) files['SHA256SUMS.txt']=Object.entries(files).map(([n,v])=>`${badInternal?'f'.repeat(64):crypto.createHash('sha256').update(v).digest('hex')}  ${n}\n`).join('');
  if(missingManifest) delete files['manifest.json'];
  return execFileSync(process.platform==='win32'?'python':'python3',['-c',
    'import io,json,sys,zipfile; b=io.BytesIO(); z=zipfile.ZipFile(b,"w",zipfile.ZIP_STORED); v=json.load(sys.stdin); [z.writestr(k,s) for k,s in v["files"].items()]; z.writestr("manifest.json",v["files"]["manifest.json"]) if v["duplicate"] else None; info=zipfile.ZipInfo("link.lua"); info.create_system=3; info.external_attr=0o120777<<16; z.writestr(info,"main.lua") if v["symlink"] else None; z.close(); sys.stdout.buffer.write(b.getvalue())'],
    {input:JSON.stringify({files,duplicate,symlink})});
}
const zipData = makeZip();
const sumsData = Buffer.from(`${crypto.createHash('sha256').update(zipData).digest('hex')}  ${zipName}\n`);
const prior = {draft:false, tag_name:'v0.0.75', body:`Automated package\n\nSource: https://github.com/Neburb/gen1recomp-legends/commit/${sha}`,
  assets:[{id:1,name:'SHA256SUMS.txt',size:sumsData.length},{id:2,name:zipName,size:zipData.length}],html_url:'https://example.test/release/v0.0.75'};
async function check({current=sha, releases=[], tags=[], allowed, rejects, assets={1:sumsData,2:zipData}, sourceSha=sha, sourceRef='refs/heads/main', trustedZip=zipData, rebuildFails=false}) {
  process.env.SOURCE_SHA=sourceSha; process.env.SOURCE_REF=sourceRef; process.env.PUBLIC_TOKEN='mock-public-read';
  let branchCalls=0, output;
  const github={rest:{repos:{listReleases:()=>{},listTags:()=>{},getBranch:async()=>{branchCalls++;return {data:{commit:{sha:current}}}},
    getReleaseAsset:async options=>{assert.equal(options.headers.authorization,'Bearer mock-public-read');assert.equal(options.headers.accept,'application/octet-stream');const bytes=assets[options.asset_id];return {data:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)}}}},
    paginate:async(fn,options)=>{assert.equal(options.headers.authorization,'Bearer mock-public-read');return fn===github.rest.repos.listTags?tags:releases}};
  const core={info:()=>{},setOutput:(name,value)=>{assert.equal(name,'allowed');output=value}};
  // Controlled source-build double; Python integration tests execute the real recipe.
  const guardedRequire = name => name !== 'node:child_process' ? require(name) : {
    execFileSync: (python, args, options) => {
      if(args[0] === 'scripts/verify_release_archive.py') return execFileSync(python, args, options);
      assert.deepEqual(Object.keys(options.env).sort(), ['PATH', 'SystemRoot', 'TEMP', 'TMP'].filter(key=>typeof process.env[key]==='string').sort());
      assert.equal(options.env.PUBLIC_TOKEN,undefined);assert.equal(options.env.INPUT_GITHUB_TOKEN,undefined);
      assert.deepEqual(args, ['scripts/isolated_release.py', '--source', 'source', '--source-sha', sourceSha, '--version', '0.0.75', '--verify-stdin']);
      execFileSync(python, ['scripts/verify_release_archive.py', '-', '0.0.75'], options);
      if(rebuildFails || !options.input.equals(trustedZip)) throw new Error('source rebuild mismatch');
    },
  };
  if(rejects) {await assert.rejects(run(github,core,guardedRequire),rejects);assert.equal(output,undefined)}
  else {await run(github,core,guardedRequire);assert.equal(output,allowed)}
  return branchCalls;
}
test('publication boundary handles freshness and rejects damaged retries',async t=>{
  await t.test('new current source is allowed',()=>check({allowed:'true'}));
  await t.test('superseded source is skipped',()=>check({current:newer,allowed:'false'}));
  await t.test('complete retry verifies bytes and avoids branch lookup',async()=>assert.equal(await check({releases:[prior],allowed:'false'}),0));
  await t.test('legacy literal newline notes are recognized',()=>check({releases:[{...prior,body:prior.body.replaceAll('\n','\\n')}],allowed:'false'}));
  const recovery = /Source release needs recovery: https:\/\/example.test\/release\/v0.0.75; follow docs\/release-recovery.md/;
  const archiveCheck = data => {
    const sum=Buffer.from(`${crypto.createHash('sha256').update(data).digest('hex')}  ${zipName}\n`);
    return {releases:[{...prior,assets:prior.assets.map(a=>({...a,size:a.id===1?sum.length:data.length}))}],assets:{1:sum,2:data},rejects:recovery};
  };
  await t.test('conflicting complete Source lines require recovery',()=>check({releases:[{...prior,body:prior.body+'\nSource: https://github.com/Neburb/gen1recomp-legends/commit/'+newer}],rejects:recovery}));
  await t.test('duplicate identical Source lines require recovery',()=>check({releases:[{...prior,body:prior.body+'\nSource: https://github.com/Neburb/gen1recomp-legends/commit/'+sha}],rejects:recovery}));
  await t.test('extra published asset requires recovery',()=>check({releases:[{...prior,assets:[...prior.assets,{id:3,name:'stale.zip',size:1}]}],rejects:recovery}));
  await t.test('valid but wrong source package requires recovery',()=>check(archiveCheck(makeZip({extra:{'other-source.txt':'self-consistent foreign package'}}))));
  await t.test('source rebuild failure cannot declare healthy',()=>check({releases:[prior],rebuildFails:true,rejects:recovery}));
  await t.test('orphan semver tag blocks a new version',()=>check({tags:[{name:'v0.0.75'}],rejects:/Release tag needs reconciliation: v0.0.75/}));
  await t.test('tag belonging to another source release permits current publication',()=>check({tags:[{name:'v0.0.75'}],releases:[{...prior,body:prior.body.replace(sha,newer)}],allowed:'true'}));
  await t.test('nonrelease tags do not block allocation',()=>check({tags:[{name:'backup-source'}],allowed:'true'}));
  await t.test('matching checksum of invalid archive still needs recovery',()=>check(archiveCheck(Buffer.from('not a zip'))));
  await t.test('wrong embedded manifest version needs recovery',()=>check(archiveCheck(makeZip({manifestVersion:'0.0.74'}))));
  await t.test('wrong embedded main version needs recovery',()=>check(archiveCheck(makeZip({mainVersion:'0.0.74'}))));
  await t.test('wrong embedded public repo needs recovery',()=>check(archiveCheck(makeZip({githubRepo:'Neburb/gen1recomp-legends'}))));
  await t.test('missing root manifest needs recovery',()=>check(archiveCheck(makeZip({missingManifest:true}))));
  await t.test('duplicate archive members need recovery',()=>check(archiveCheck(makeZip({duplicate:true}))));
  for(const [name,opts] of Object.entries({
    'embedded digest mismatch':{badInternal:true},
    'missing embedded checksum':{missingInternal:true},
    'traversal member':{extra:{'../escape.lua':'payload'}},
    'absolute member':{extra:{'/escape.lua':'payload'}},
    'Windows member':{extra:{'C:/escape.lua':'payload'}},
    'backslash traversal':{extra:{'..\\escape.lua':'payload'}},
    'nested env directory':{extra:{'config/.env.local/key':'secret'}},
    'root env directory':{extra:{'.env/production':'secret'}},
    'npm credentials':{extra:{'config/.npmrc':'secret'}},
    'ssh key':{extra:{'.ssh/id_rsa':'secret'}},
    'aws credentials':{extra:{'.aws/credentials':'secret'}},
    'key extension':{extra:{'config/auth.key':'secret'}},
    'blocked layout':{extra:{'.git/config':'payload'}},
    'symlink member':{symlink:true},
  })) await t.test(name,()=>check(archiveCheck(makeZip(opts))));
  await t.test('matching digest cannot hide corrupt CRC',()=>{const corrupt=Buffer.from(zipData);const offset=corrupt.indexOf('crc fixture payload');assert(offset>=0);corrupt[offset]^=1;return check(archiveCheck(corrupt))});
  await t.test('matching draft blocks allocation with recovery URL',()=>check({releases:[{...prior,draft:true}],rejects:recovery}));
  await t.test('matching draft blocks even alongside a published release',()=>check({releases:[prior,{...prior,draft:true}],rejects:recovery}));
  await t.test('duplicate published sources require recovery',()=>check({releases:[prior,prior],rejects:recovery}));
  await t.test('missing assets require recovery',()=>check({releases:[{...prior,assets:[]}],rejects:recovery}));
  await t.test('wrong version ZIP requires recovery',()=>check({releases:[{...prior,assets:prior.assets.map(a=>a.id===2?{...a,name:'stadium_realtime_combat-0.0.76.zip'}:a)}],rejects:recovery}));
  await t.test('oversized compressed ZIP stops before download',()=>check({releases:[{...prior,assets:prior.assets.map(a=>({...a,size:a.id===2?128*1024*1024+1:a.size}))}],assets:{},rejects:recovery}));
  await t.test('oversized checksum stops before download',()=>check({releases:[{...prior,assets:prior.assets.map(a=>({...a,size:a.id===1?4097:a.size}))}],assets:{},rejects:recovery}));
  await t.test('zero size ZIP requires recovery',()=>check({releases:[{...prior,assets:prior.assets.map(a=>({...a,size:a.id===2?0:a.size}))}],rejects:recovery}));
  await t.test('invalid release tag requires recovery',()=>check({releases:[{...prior,tag_name:'other'}],rejects:recovery}));
  await t.test('checksum for different ZIP requires recovery',()=>check({releases:[prior],assets:{1:Buffer.from(sumsData.toString().replace('0.0.75','0.0.76')),2:zipData},rejects:recovery}));
  await t.test('wrong digest requires recovery',()=>check({releases:[prior],assets:{1:Buffer.from('f'.repeat(64)+`  ${zipName}\n`),2:zipData},rejects:recovery}));
  await t.test('truncated ZIP requires recovery',()=>check({releases:[prior],assets:{1:sumsData,2:zipData.subarray(1)},rejects:recovery}));
  await t.test('duplicate ZIP asset requires recovery',()=>check({releases:[{...prior,assets:[...prior.assets,prior.assets[1]]}],rejects:recovery}));
  await t.test('malformed checksum requires recovery',()=>check({releases:[{...prior,assets:prior.assets.map(a=>a.id===1?{...a,size:4}:a)}],assets:{1:Buffer.from('bad\n'),2:zipData},rejects:recovery}));
  await t.test('source A draft blocks source B dispatch',()=>check({releases:[{...prior,draft:true,body:prior.body.replace(sha,newer)}],rejects:recovery}));
  await t.test('draft without Source blocks allocation',()=>check({releases:[{...prior,draft:true,body:''}],rejects:recovery}));
  await t.test('invalid source ref fails',()=>check({sourceRef:'refs/heads/other',rejects:/Invalid source ref/}));
  await t.test('invalid SHA fails',()=>check({sourceSha:'bad',rejects:/Invalid source SHA/}));
});
const preflight = workflow.match(/        id: source[\s\S]*?          script: \|\n([\s\S]*?)\n      - name: Prepare trusted isolated packaging runtime/)[1].split('\n').map(line=>line.slice(12)).join('\n');
const runPreflight = new (Object.getPrototypeOf(async function() {}).constructor)('github','core',preflight);
test('private source cannot reach package execution before provenance succeeds',async t=>{
  const names=['Check out private source commit','Determine public release version','Build installable public ZIP','Check freshness and duplicate source at publication boundary'];
  for(const name of names) assert(workflow.includes(`      - name: ${name}\n        if: steps.source.outputs.allowed == 'true'`));
  assert(workflow.indexOf('python3 scripts/isolated_release.py')>workflow.indexOf('id: source'));
  const checkout=workflow.slice(workflow.indexOf('      - name: Check out public'),workflow.indexOf('      - name: Validate dispatch'));
  assert.match(checkout,/persist-credentials: false/);
  assert.match(workflow,/test "\$SOURCE_REF" = "refs\/heads\/main"/);
  const checkPreflight=async(current,error)=>{
    process.env.SOURCE_SHA=sha;let output,executed=false;
    const github={rest:{repos:{getBranch:async()=>{if(error) throw error;return {data:{commit:{sha:current}}}}}}};
    const core={info:()=>{},setOutput:(n,v)=>{assert.equal(n,'allowed');output=v}};
    if(error) await assert.rejects(runPreflight(github,core),/API failure/);
    else await runPreflight(github,core);
    if(output==='true') executed=true;
    return executed;
  };
  await t.test('current main permits build',async()=>assert.equal(await checkPreflight(sha),true));
  await t.test('non-main SHA cannot execute build',async()=>assert.equal(await checkPreflight(newer),false));
  await t.test('API failure cannot execute build',async()=>assert.equal(await checkPreflight(null,new Error('API failure')),false));
});
