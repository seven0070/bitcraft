# Future simulated world — DRAFT seed for MiroFish (not yet submitted)

## Prediction question
What does everyday life, work, and public conversation look like in a near-future world (2035) where AI agents, creators, and automated earning are normal — and what trajectories, tensions, and opportunities emerge from it?

## Seed world (draft, to be confirmed by Sanath)
- Setting: Bangalore, India, in 2035, connected to the wider world — not a utopia, not a collapse.
- People/agents to emerge from the seed: students and creators, gig/freelance workers, small-business owners, AI-agent builders, policymakers, journalists, ordinary families, investors.
- Forces in play: AI agents doing most digital work, human approval only for money and big decisions; creator economy and short video; automation of freelancing/clipping; cost, jobs, and trust in AI-made content; regulation and platform power; climate, transport, and city life in Bangalore.
- What to watch in the simulation: how work and income change, how public opinion forms on social platforms (Twitter/Reddit-style in MiroFish), what new conflicts appear, and what a creator/builder in Bangalore should do differently.

## How MiroFish will use this
MiroFish workflow: seed extraction -> knowledge graph (Zep Cloud) -> persona/agent generation -> dual-platform simulation (Twitter + Reddit-style, OASIS) -> report agent -> interactive world.
Inputs needed before a run: a project name, this seed text, and a prediction requirement in natural language (above). MiroFish then generates max rounds and agent profiles itself — no manual round count needed.
Recommended first run: under 40 rounds (README warning: LLM consumption is high).

## Blockers (2026-10-25)
- Backend refuses to start without LLM_API_KEY and ZEP_API_KEY.
- Zep Cloud: free signup at https://app.getzep.com/ — no key on file yet.
- LLM: candidate is the existing NVIDIA OpenAI-compatible key already used for OpenDots (nemotron-3-super-120b-a12b), but reuse for MiroFish is NOT yet confirmed by Sanath. Alternative: Qwen-plus via Alibaba Bailian, as MiroFish recommends.
- No simulation has been created or run yet. This file is only a draft seed.
