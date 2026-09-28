const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/publish.yml'), 'utf8').replaceAll('\r\n', '\n');
const guard = workflow.match(/        id: boundary[\s\S]*?          script: \|\n([\s\S]*?)\n      - name: Publish GitHub Release/)[1].split('\n').map(line => line.slice(12)).join('\n');
assert.match(workflow, /if: steps\.boundary\.outputs\.allowed == 'true'/);
const run = new (Object.getPrototypeOf(async function() {}).constructor)('github', 'core', 'require', guard);
const sha = 'a'.repeat(40), newer = 'b'.repeat(40);
const zipName = 'stadium_realtime_combat-0.0.75.zip';
const zipData = Buffer.from('fixture archive bytes');
const sumsData = Buffer.from(`${crypto.createHash('sha256').update(zipData).digest('hex')}  ${zipName}\n`);
const prior = {draft:false, tag_name:'v0.0.75', body:`Automated package\n\nSource: https://github.com/Neburb/gen1recomp-legends/commit/${sha}`,
  assets:[{id:1,name:'SHA256SUMS.txt',size:sumsData.length},{id:2,name:zipName,size:zipData.length}],html_url:'https://example.test/release/v0.0.75'};
async function check({current=sha, releases=[], allowed, rejects, assets={1:sumsData,2:zipData}, sourceSha=sha, sourceRef='refs/heads/main'}) {
  process.env.SOURCE_SHA=sourceSha; process.env.SOURCE_REF=sourceRef; process.env.PUBLIC_TOKEN='mock-public-read';
  let branchCalls=0, output;
  const github={rest:{repos:{listReleases:()=>{},getBranch:async()=>{branchCalls++;return {data:{commit:{sha:current}}}},
    getReleaseAsset:async options=>{assert.equal(options.headers.authorization,'Bearer mock-public-read');assert.equal(options.headers.accept,'application/octet-stream');const bytes=assets[options.asset_id];return {data:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)}}}},
    paginate:async(fn,options)=>{assert.equal(options.headers.authorization,'Bearer mock-public-read');return releases}};
  const core={info:()=>{},setOutput:(name,value)=>{assert.equal(name,'allowed');output=value}};
  if(rejects) {await assert.rejects(run(github,core,require),rejects);assert.equal(output,undefined)}
  else {await run(github,core,require);assert.equal(output,allowed)}
  return branchCalls;
}
test('publication boundary handles freshness and rejects damaged retries',async t=>{
  await t.test('new current source is allowed',()=>check({allowed:'true'}));
  await t.test('superseded source is skipped',()=>check({current:newer,allowed:'false'}));
  await t.test('complete retry verifies bytes and avoids branch lookup',async()=>assert.equal(await check({releases:[prior],allowed:'false'}),0));
  await t.test('legacy literal newline notes are recognized',()=>check({releases:[{...prior,body:prior.body.replaceAll('\n','\\n')}],allowed:'false'}));
  const recovery = /Source release needs recovery: https:\/\/example.test\/release\/v0.0.75; follow docs\/release-recovery.md/;
  await t.test('matching draft blocks allocation with recovery URL',()=>check({releases:[{...prior,draft:true}],rejects:recovery}));
  await t.test('matching draft blocks even alongside a published release',()=>check({releases:[prior,{...prior,draft:true}],rejects:recovery}));
  await t.test('duplicate published sources require recovery',()=>check({releases:[prior,prior],rejects:recovery}));
  await t.test('missing assets require recovery',()=>check({releases:[{...prior,assets:[]}],rejects:recovery}));
  await t.test('wrong version ZIP requires recovery',()=>check({releases:[{...prior,assets:prior.assets.map(a=>a.id===2?{...a,name:'stadium_realtime_combat-0.0.76.zip'}:a)}],rejects:recovery}));
  await t.test('zero size ZIP requires recovery',()=>check({releases:[{...prior,assets:prior.assets.map(a=>({...a,size:a.id===2?0:a.size}))}],rejects:recovery}));
  await t.test('invalid release tag requires recovery',()=>check({releases:[{...prior,tag_name:'other'}],rejects:recovery}));
  await t.test('checksum for different ZIP requires recovery',()=>check({releases:[prior],assets:{1:Buffer.from(sumsData.toString().replace('0.0.75','0.0.76')),2:zipData},rejects:recovery}));
  await t.test('wrong digest requires recovery',()=>check({releases:[prior],assets:{1:Buffer.from('f'.repeat(64)+`  ${zipName}\n`),2:zipData},rejects:recovery}));
  await t.test('truncated ZIP requires recovery',()=>check({releases:[prior],assets:{1:sumsData,2:zipData.subarray(1)},rejects:recovery}));
  await t.test('duplicate ZIP asset requires recovery',()=>check({releases:[{...prior,assets:[...prior.assets,prior.assets[1]]}],rejects:recovery}));
  await t.test('malformed checksum requires recovery',()=>check({releases:[{...prior,assets:prior.assets.map(a=>a.id===1?{...a,size:4}:a)}],assets:{1:Buffer.from('bad\n'),2:zipData},rejects:recovery}));
  await t.test('different source draft does not block new source',()=>check({releases:[{...prior,draft:true,body:prior.body.replace(sha,newer)}],allowed:'true'}));
  await t.test('invalid source ref fails',()=>check({sourceRef:'refs/heads/other',rejects:/Invalid source ref/}));
  await t.test('invalid SHA fails',()=>check({sourceSha:'bad',rejects:/Invalid source SHA/}));
});
