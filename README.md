# Bram: an NPC with a brain

A top-down Python/Pygame village with one NPC, Bram, who isn't scripted. He sees with raycasts, hears through walls, remembers what you did, and every quarter of a second picks what to do with Utility AI. Rob him while he's watching and he'll chase you. Rob him while he's away and he might still work out it was you.

## Run it

Python 3.10 or newer.

```bash
pip install -r requirements.txt
python main.py
```

| Option | What it does |
| --- | --- |
| `--no-capture` | don't write session logs or screenshots to `sessions/` |
| `--seed 48` | world seed (runs are deterministic, so the same seed replays the same day) |
| `--frames 600` | quit after N frames (handy for quick tests) |

## Controls

| Key | Action |
| --- | --- |
| WASD | move |
| E | steal from the chest / pick up food or coins |
| G | give food to Bram |
| T | spawn a wolf |
| F / C | drop food / a coin at the mouse |
| F1 – F5 | toggle overlays: overhead info, vision cones, A* paths, brain panel, memory ghosts |
| Space | pause |
| [ ] | slow down / speed up time |
| F9 / F12 | drop a marker / take a screenshot (saved under `sessions/`) |

Things to try: steal right in front of him; hang around the chest, wait for him to leave, then steal; give him food until he likes you again; spawn a wolf.

## How his brain works

Every frame runs one loop (`brain/brain.py`):

1. **Sense** (`brain/perception.py`): a 110° cone, 7.5 tiles long, cut off by walls with 40 rays. He hears anything within 5 tiles, and sound goes through walls.
2. **Remember** (`brain/memory.py`): trust in the player (starts at 0.50), thefts, gifts, where he last saw you, a breadcrumb every second you're visible (last 40 kept), where food and coins are, and how much gold he *believes* is in his chest.
3. **Feel** (`brain/drives.py`): hunger and greed rise over time; fear spikes when a threat appears, then decays.
4. **Think** (`brain/utility.py`, `brain/actions.py`): every 0.25 s he scores 11 actions (Wander, Eat, Collect Coin, Deposit Gold, Check Stash, Guard Chest, Confront Thief, Investigate, Follow Friend, Ask For Food, Flee). Each score is a weight times its considerations multiplied together; the highest wins.
5. **Act**: the winning action runs every frame until something scores higher.

Nothing says "if the player steals, get angry". He gets angry because his trust crashed, chases you because Confront out-scored everything, and figures out a theft he didn't see by checking which breadcrumbs were near the chest in the last 45 seconds.

Every tuning number (speeds, ranges, rates, trust penalties) lives in `config.py`.

## Files

```
main.py            game loop, input, overlays
config.py          every tuning constant
world.py           map, walls, chest, food and coins, DDA raycasting
entities.py        player and wolf
npc.py             Bram's body: movement, head turning, speech bubbles
pathfinding.py     A* on the tile grid
telemetry.py       everything drawn to make the brain visible (cones, panel, bubbles)
capture.py         session logs and screenshots (sessions/)
brain/
  brain.py         the sense, remember, feel, think, act loop
  perception.py    vision cone and hearing
  memory.py        trust, breadcrumbs, beliefs
  drives.py        hunger, fear, greed
  utility.py       considerations, scoring, the reasoner
  actions.py       the 11 actions
  context.py       what an action can read while scoring
```
