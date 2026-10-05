// The ordinary dispatch requires current main. An operator may explicitly pin
// a validated snapshot when concurrent development advances main during a build.
async function sourceAllowed(github, core, sha, pinned, approvedRun = require('./approved_source.json')) {
  if (!/^[0-9a-f]{40}$/.test(sha)) throw new Error('Invalid source SHA');
  const repo = {owner: 'Neburb', repo: 'gen1recomp-legends'};
  const {data: branch} = await github.rest.repos.getBranch({...repo, branch: 'main'});
  if (!pinned) {
    if (branch.commit.sha !== sha) core.info(`Skip superseded source ${sha}; main is ${branch.commit.sha}`);
    return branch.commit.sha === sha;
  }
  const {data: comparison} = await github.rest.repos.compareCommits({
    ...repo, base: sha, head: branch.commit.sha,
  });
  if (!['ahead', 'identical'].includes(comparison.status) || comparison.merge_base_commit.sha !== sha) {
    throw new Error('Pinned source is not an ancestor of current main');
  }
  let runs;
  try {
    runs = await github.paginate(github.rest.actions.listWorkflowRuns, {
      ...repo, workflow_id: 'ci.yml', head_sha: sha, event: 'push', per_page: 100,
    });
  } catch (error) {
    // A contents-only source token cannot read Actions. The operator may record
    // an exact-source CI approval in this trusted recipe; payloads cannot grant it.
    if (error.status !== 403 || !approvedRun || approvedRun.head_sha !== sha
      || !(Date.parse(approvedRun.expires_at) > Date.now())
      || approvedRun.html_url !== `https://github.com/Neburb/gen1recomp-legends/actions/runs/${approvedRun.id}`) throw error;
    core.info(`Use recorded exact-source CI approval verified at ${approvedRun.verified_at}`);
    runs = [approvedRun];
  }
  const matching = runs.filter(run => run.head_sha === sha && run.head_branch === 'main'
    && run.event === 'push' && run.path === '.github/workflows/ci.yml');
  matching.sort((a, b) => b.id - a.id);
  const latest = matching[0];
  if (!latest || latest.status !== 'completed' || latest.conclusion !== 'success') {
    throw new Error('Pinned source requires successful latest main CI for this exact SHA');
  }
  core.info(`Publish explicitly pinned main snapshot ${sha}; CI ${latest.id} succeeded`);
  return true;
}
module.exports = {sourceAllowed};
