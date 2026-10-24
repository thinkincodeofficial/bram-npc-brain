"""Global tuning constants. Every number that shapes NPC behaviour lives here
so it can be tweaked (and quoted on video) from one place."""

# --- Display -----------------------------------------------------------------
TILE = 32
GRID_W, GRID_H = 30, 22
MAP_W, MAP_H = GRID_W * TILE, GRID_H * TILE
PANEL_W = 340
SCREEN_W, SCREEN_H = MAP_W + PANEL_W, MAP_H
FPS = 60
MAX_DT = 0.05            # clamp long frames so physics never explodes
SEED = 48                # deterministic runs make re-takes reproducible
TIME_SCALES = [0.25, 0.5, 1.0, 2.0, 4.0]

# --- Movement (pixels / second) -----------------------------------------------
PLAYER_SPEED = 165
NPC_WALK_SPEED = 90
NPC_RUN_SPEED = 155
WOLF_SPEED = 120
NPC_TURN_RATE = 300      # degrees / second the head can rotate
INTERACT_RANGE = 1.4 * TILE

# --- Perception ----------------------------------------------------------------
VISION_RANGE = 7.5 * TILE
VISION_FOV = 110         # degrees, full cone width
HEARING_RADIUS = 5 * TILE
TOUCH_RADIUS = 1.2 * TILE  # always sensed, even behind the NPC
CONE_RAYS = 40           # rays used to draw the wall-clipped vision cone
STASH_INSPECT_RANGE = 2.5 * TILE

# --- Drives (0..1, change per second) -----------------------------------------
HUNGER_RATE = 0.010
GREED_RATE = 0.006
FEAR_DECAY = 0.10
STARTLE_FEAR = 0.85          # fear floor on first sighting of a threat
EAT_SATIATION = 0.6
GIFT_SATIATION = 0.5
DEPOSIT_GREED_RELIEF = 0.12
THEFT_GREED_SPIKE = 0.25

# --- Memory -------------------------------------------------------------------
TRUST_START = 0.5
TRUST_DRIFT = 0.004          # per second, toward the (grudge-adjusted) baseline
TRUST_WITNESSED_THEFT = -0.35
TRUST_DEDUCED_THEFT = -0.20
TRUST_GIFT = 0.15
TRUST_RESTITUTION = 0.05
GRUDGE_PER_THEFT = 0.08      # each theft permanently lowers the trust baseline
GOODWILL_PER_GIFT = 0.04     # each gift permanently raises it
RESOURCE_MEMORY_TTL = 60.0   # seconds before an unseen resource is forgotten
SIGHTING_INTERVAL = 1.0      # seconds between breadcrumbs in the sighting buffer
SIGHTING_BUFFER = 40         # breadcrumbs kept per entity
EVENT_LOG_SIZE = 9
SUSPECT_WINDOW = 45.0        # how far back the NPC looks for a theft suspect
SUSPECT_RADIUS = 4 * TILE

# --- Decision engine ------------------------------------------------------------
DECISION_INTERVAL = 0.25     # seconds between full utility re-evaluations
COMMITMENT_BONUS = 0.08      # inertia added to the running action (anti-dither)

# --- Wolf (threat) ----------------------------------------------------------------
WOLF_LIFETIME = 30.0
WOLF_SIGHT = 7 * TILE
WOLF_BITE_RANGE = 18

# --- Colours ----------------------------------------------------------------------
BG = (18, 20, 26)
FLOOR_A = (54, 58, 66)
FLOOR_B = (50, 54, 62)
WALL = (92, 78, 64)
WALL_TOP = (124, 106, 86)
HOME_RUG = (84, 60, 92)
PANEL_BG = (14, 16, 22)
TEXT = (230, 232, 238)
TEXT_DIM = (140, 146, 160)
ACCENT = (255, 196, 64)
PLAYER_COL = (80, 160, 255)
NPC_COL = (255, 150, 70)
WOLF_COL = (150, 150, 160)
FOOD_COL = (220, 60, 60)
COIN_COL = (250, 210, 60)
CHEST_COL = (140, 90, 40)
HUNGER_COL = (240, 120, 60)
FEAR_COL = (180, 100, 255)
GREED_COL = (250, 210, 60)
TRUST_COL = (90, 220, 140)
DISTRUST_COL = (235, 70, 70)
