export const meta = {
  name: 'dev-loop',
  description: 'Self-improvement loop for bit-bridle: assess → triage → implement → independently validate → auto-commit. No agent grades its own work.',
  whenToUse: 'Run when you want the harness to incrementally improve itself for one or more rounds.',
  phases: [
    { title: 'Assess', detail: 'parallel read-only assessors, one per lens' },
    { title: 'Triage', detail: 'single synthesizer dedups, scores, picks disjoint top-K' },
    { title: 'Implement+Validate', detail: 'per item: implement in an isolated worktree, then a DIFFERENT agent validates' },
    { title: 'Integrate', detail: 'merge & commit only the changes that passed validation' },
  ],
}

// ---- knobs (override via args) -------------------------------------------
const cfg = {
  rounds: args?.rounds ?? 1,          // how many assess→integrate rounds
  perRound: args?.perRound ?? 3,      // max improvements implemented per round
  lenses: args?.lenses ?? [
    'correctness & bugs (logic errors, edge cases, broken behavior)',
    'roadmap features from README (approval prompts, persistence/resume, token accounting, MCP, parallel tools) — pick the smallest valuable slice',
    'code quality & simplification (dead code, duplication, clarity) without changing behavior',
    'test coverage (there are currently NO automated tests — adding a pytest suite is high value)',
    'robustness & error handling (network/timeout/malformed tool args, bad config)',
    'docs accuracy (README/.env.example match the actual code & flags)',
  ],
}

const ASSESS_SCHEMA = {
  type: 'object',
  properties: {
    improvements: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          rationale: { type: 'string' },
          files: { type: 'array', items: { type: 'string' }, description: 'Repo-relative paths this change would touch/create.' },
          acceptance_criteria: { type: 'array', items: { type: 'string' }, description: 'Concrete, checkable conditions a validator can verify (commands that must pass, behavior that must hold).' },
          size: { type: 'string', enum: ['S', 'M', 'L'] },
          risk: { type: 'string', enum: ['low', 'medium', 'high'] },
        },
        required: ['title', 'rationale', 'files', 'acceptance_criteria', 'size', 'risk'],
      },
    },
  },
  required: ['improvements'],
}

const TRIAGE_SCHEMA = {
  type: 'object',
  properties: {
    selected: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          rationale: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } },
          acceptance_criteria: { type: 'array', items: { type: 'string' } },
        },
        required: ['title', 'rationale', 'files', 'acceptance_criteria'],
      },
      description: 'Top items for THIS round. MUST have pairwise-disjoint file sets so they can be implemented in parallel without conflict.',
    },
    dropped_note: { type: 'string', description: 'Brief note on what was deduped/deferred and why.' },
  },
  required: ['selected'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' },
    commands_run: { type: 'array', items: { type: 'string' } },
    criteria_results: {
      type: 'array',
      items: {
        type: 'object',
        properties: { criterion: { type: 'string' }, met: { type: 'boolean' }, evidence: { type: 'string' } },
        required: ['criterion', 'met', 'evidence'],
      },
    },
    regressions: { type: 'string', description: 'Any regression or breakage found, or "none".' },
    summary: { type: 'string' },
  },
  required: ['pass', 'criteria_results', 'summary'],
}

const REPO = '/Users/bdoss/code/bit-bridle-harness'

function keyOf(item) {
  return item.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40)
}

const accepted = []   // merged improvements across all rounds
const log_lines = []

for (let round = 1; round <= cfg.rounds; round++) {
  log(`Round ${round}/${cfg.rounds} — assessing across ${cfg.lenses.length} lenses`)

  // ---- 1. ASSESS (parallel, read-only) ----------------------------------
  phase('Assess')
  const alreadyDone = accepted.map(a => `- ${a.title}`).join('\n') || '(none yet)'
  const assessments = await parallel(cfg.lenses.map((lens, i) => () =>
    agent(
      `You are assessing the bit-bridle coding-agent harness at ${REPO} for improvements.\n` +
      `LENS (focus ONLY on this): ${lens}\n\n` +
      `Read the relevant source under src/bit_bridle/ and the README. Propose concrete, high-value, SMALL improvements through this lens.\n` +
      `Already implemented in prior rounds (do NOT re-propose):\n${alreadyDone}\n\n` +
      `For each improvement give exact files to touch and concrete acceptance_criteria a separate validator can check by running commands. Read-only: do NOT modify anything.`,
      { label: `assess:lens${i + 1}`, phase: 'Assess', schema: ASSESS_SCHEMA, agentType: 'Explore' }
    )
  ))
  const candidates = assessments.filter(Boolean).flatMap(a => a.improvements)
  log(`Round ${round}: ${candidates.length} candidate improvements proposed`)
  if (!candidates.length) { log(`Round ${round}: nothing proposed — stopping early.`); break }

  // ---- 2. TRIAGE (single synthesizer; does NOT implement) ----------------
  phase('Triage')
  const triage = await agent(
    `You are the triage lead for the bit-bridle self-improvement loop. Here are candidate improvements proposed by independent assessors:\n\n` +
    JSON.stringify(candidates, null, 2) +
    `\n\nDedup near-duplicates, score by value/effort and risk, and select up to ${cfg.perRound} to implement THIS round.\n` +
    `HARD CONSTRAINT: the selected items must have PAIRWISE-DISJOINT file sets (no two selected items touch the same file) so they can be implemented in parallel safely. Prefer small, low-risk, high-value items. Do not implement anything yourself.`,
    { label: 'triage', phase: 'Triage', schema: TRIAGE_SCHEMA }
  )
  const selected = (triage?.selected ?? []).slice(0, cfg.perRound)
  if (!selected.length) { log(`Round ${round}: triage selected nothing — stopping early.`); break }
  log(`Round ${round}: implementing ${selected.length} — ${selected.map(s => s.title).join('; ')}`)

  // ---- 3+4. IMPLEMENT (isolated worktree) then VALIDATE (different agent) -
  // pipeline => each item validates as soon as its implementation lands; no barrier.
  const results = await pipeline(
    selected.map((item, i) => ({ item, branch: `dev-loop/r${round}-i${i + 1}-${keyOf(item)}` })),

    // stage 1: implement — isolated worktree, commit on its own branch.
    async ({ item, branch }) =>
      agent(
        `You are implementing ONE improvement to the bit-bridle harness. Work ONLY within the files listed; do not touch others.\n\n` +
        `TITLE: ${item.title}\nRATIONALE: ${item.rationale}\nFILES: ${item.files.join(', ')}\n` +
        `ACCEPTANCE CRITERIA (you must make these true):\n${item.acceptance_criteria.map(c => '- ' + c).join('\n')}\n\n` +
        `Steps: create and switch to a new git branch named exactly "${branch}"; make the change; keep it minimal and consistent with the surrounding code; then "git add -A" and commit with a clear message. ` +
        `Do NOT judge or grade your own work and do NOT merge into main — a separate validator will assess it. Report what you changed.`,
        { label: `impl:${branch}`, phase: 'Implement+Validate', isolation: 'worktree' }
      ).then(report => ({ item, branch, report })),

    // stage 2: validate — DIFFERENT agent, given criteria from ASSESS (not the implementer's report).
    async (built, original, i) => {
      if (!built) return null
      const { item, branch } = built
      const verdict = await agent(
        `You are an INDEPENDENT validator. You did NOT write this code. Be skeptical and try to find regressions.\n\n` +
        `A change was committed on git branch "${branch}" in the repo at ${REPO}.\n` +
        `Check it out in your isolated worktree: "git checkout ${branch}".\n\n` +
        `INTENDED IMPROVEMENT: ${item.title}\nACCEPTANCE CRITERIA (verify each):\n${item.acceptance_criteria.map(c => '- ' + c).join('\n')}\n\n` +
        `Validate rigorously: set up the env if needed (python3 -m venv .venv && . .venv/bin/activate && pip install -e .), run any tests/lint/build, import-smoke the package, and exercise the changed behavior. ` +
        `Verify EACH acceptance criterion with evidence, and check nothing else broke. Pass ONLY if all criteria are met and there are no regressions.`,
        { label: `validate:${branch}`, phase: 'Implement+Validate', isolation: 'worktree', schema: VERDICT_SCHEMA }
      )
      return { item, branch, verdict }
    }
  )

  // ---- 5. INTEGRATE (auto-commit only what passed) -----------------------
  phase('Integrate')
  const passing = results.filter(Boolean).filter(r => r.verdict?.pass)
  const failed = results.filter(Boolean).filter(r => !r.verdict?.pass)
  failed.forEach(f => log(`✗ rejected: ${f.item.title} — ${f.verdict?.regressions || f.verdict?.summary || 'failed validation'}`))

  if (passing.length) {
    const integ = await agent(
      `You are the integrator for the bit-bridle self-improvement loop, working in ${REPO} on the "main" branch.\n` +
      `These branches passed INDEPENDENT validation and should be merged into main. Their file sets are disjoint, so merges should be clean:\n` +
      passing.map(p => `- ${p.branch}  (${p.item.title})`).join('\n') +
      `\n\nFor each branch: "git merge --no-ff <branch>" into main. If any unexpected conflict arises, resolve it conservatively preserving both intents; if truly unresolvable, ABORT that one merge and report it as skipped. ` +
      `Do not modify code beyond conflict resolution. Report which branches merged and which were skipped.`,
      { label: `integrate:r${round}`, phase: 'Integrate' }
    )
    log_lines.push(`Round ${round} integration: ${integ.slice(0, 300)}`)
    passing.forEach(p => accepted.push({ round, title: p.item.title, branch: p.branch }))
  }
  log(`Round ${round} complete: ${passing.length} merged, ${failed.length} rejected`)
}

return {
  rounds_run: cfg.rounds,
  accepted_count: accepted.length,
  accepted,
  notes: log_lines,
}
