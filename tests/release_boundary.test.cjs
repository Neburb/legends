const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/publish.yml'), 'utf8');
const guard = workflow.match(/        id: boundary[\s\S]*?          script: \|\n([\s\S]*?)\n      - name: Publish GitHub Release/)[1].split('\n').map(line=>line.slice(12)).join('\n');
assert.match(workflow, /if: steps\.boundary\.outputs\.allowed == 'true'/);
const run = new (Object.getPrototypeOf(async function(){}).constructor)('github', 'core', guard);
const sha = 'a'.repeat(40), newer = 'b'.repeat(40);
process.env.SOURCE_SHA = sha; process.env.SOURCE_REF = 'refs/heads/main';
process.env.PUBLIC_TOKEN = 'mock-public-read';
async function check({current=sha, releases=[], allowed, rejects=false}) {
  let branchCalls=0, output;
  const github = {rest:{repos:{listReleases:()=>{}, getBranch:async()=>{branchCalls++;return {data:{commit:{sha:current}}}}}},
    paginate:async(fn, options)=>{assert.equal(options.headers.authorization, 'Bearer mock-public-read');return releases}};
  const core={info:()=>{},setOutput:(name,value)=>{assert.equal(name,'allowed');output=value}};
  if (rejects) await assert.rejects(run(github,core));
  else {await run(github,core);assert.equal(output,allowed)}
  return branchCalls;
}
(async()=>{
  await check({allowed:'true'});
  await check({current:newer,allowed:'false'}); // source moved after the sender check
  const prior={draft:false,body:`Automated package\n\nSource: https://github.com/Neburb/gen1recomp-legends/commit/${sha}`,assets:[{name:'SHA256SUMS.txt'},{name:'stadium_realtime_combat-0.0.75.zip'}],html_url:'release'};
  assert.equal(await check({releases:[prior],allowed:'false'}),0); // retry: no second version
  await check({releases:[{...prior,body:prior.body.replaceAll('\n','\\n')}],allowed:'false'}); // existing release notes
  await check({releases:[{...prior,assets:[]}],rejects:true});
  await check({releases:[{...prior,draft:true}],allowed:'true'});
  process.env.SOURCE_REF='refs/heads/other';await check({rejects:true});
  process.env.SOURCE_REF='refs/heads/main';process.env.SOURCE_SHA='bad';await check({rejects:true});
  console.log('8 receiver boundary cases pass; no GitHub publication performed.');
})().catch(e=>{console.error(e);process.exitCode=1});
