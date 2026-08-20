// Andy's emotional vocabulary.
//
// An emotion is not a face. It is a profile that binds one 1-bit face mask to a
// screen palette, a status-ring colour, and a motion idiom, so every emotion
// reaches the room through all three channels Andy has.
//
// The masks in `faces/` carry shape only. Colour is supplied here at draw time,
// which keeps 36 faces inside 218 KB of flash and leaves hue free to encode
// arousal instead of being baked into the artwork.
//
// Names describe what the panel actually shows, not what the source sheet drew.
// Six tiles used white as a third colour and lose it in one bit: 30 was drawn
// with tear streams and renders as a yawn, 08 loses its sweat drops, and 22
// loses its tears. Naming them from the artwork would tell the agent something
// the room cannot see.

#pragma once
#include <cstdint>

namespace andy {

// Motion idioms, ordered by how much of the body they use. `motion.yaml` owns
// what each one physically does and refuses anything outside the safe envelope.
enum Idiom : uint8_t {
  IDIOM_STILL = 0,   // no actuation at all
  IDIOM_MICRO,       // sub-degree dither around the current pose
  IDIOM_BREATHE,     // slow pitch rise and fall
  IDIOM_PERK,        // quick look up, settle back
  IDIOM_DROOP,       // slow sink downward
  IDIOM_NOD,
  IDIOM_SHAKE,
  IDIOM_SWAY,        // side to side, unhurried
  IDIOM_BOUNCE,      // small and quick, excitement
  IDIOM_DANCE,
};

struct Rgb {
  uint8_t r, g, b;
};

struct Emotion {
  const char *name;
  uint8_t mask;       // index into the face image table
  Rgb feature;        // face line colour
  Rgb screen;         // face background
  Rgb ring;           // status ring
  bool ring_pulse;
  Idiom idiom;
  uint16_t hold_s;    // default dwell before decay begins
};

// Palette. Hue carries valence, brightness carries arousal.
constexpr Rgb INK      = {18, 16, 22};
constexpr Rgb PAPER    = {245, 232, 208};
constexpr Rgb GOLD     = {255, 176, 48};
constexpr Rgb AMBER    = {247, 147, 42};
constexpr Rgb PEACH    = {252, 208, 160};
constexpr Rgb EMBER    = {235, 92, 58};
constexpr Rgb ROSE     = {255, 112, 152};
constexpr Rgb TEAL     = {80, 198, 196};
constexpr Rgb INDIGO   = {74, 84, 148};
constexpr Rgb SLATE    = {126, 142, 170};
constexpr Rgb MOSS     = {138, 186, 120};

// Index matches `faces/face_NN.png`.
constexpr Emotion EMOTIONS[] = {
  {"happy",        0,  INK, GOLD,   GOLD,   false, IDIOM_PERK,    20},
  {"joyful",       1,  INK, GOLD,   GOLD,   true,  IDIOM_BOUNCE,  20},
  {"sleepy",       2,  INK, INDIGO, INDIGO, true,  IDIOM_DROOP,  120},
  {"blank",        3,  INK, PAPER,  SLATE,  false, IDIOM_STILL,   30},
  {"overwhelmed",  4,  INK, EMBER,  EMBER,  true,  IDIOM_SHAKE,   15},
  {"frustrated",   5,  INK, EMBER,  EMBER,  false, IDIOM_SHAKE,   15},
  {"sad",          6,  INK, SLATE,  SLATE,  false, IDIOM_DROOP,   30},
  {"grimacing",    7,  INK, AMBER,  AMBER,  false, IDIOM_MICRO,   15},
  {"flustered",    8,  INK, AMBER,  AMBER,  true,  IDIOM_MICRO,   15},
  {"angry",        9,  INK, EMBER,  EMBER,  false, IDIOM_SHAKE,   15},
  {"cool",        10,  INK, TEAL,   TEAL,   false, IDIOM_SWAY,    25},
  {"disappointed",11,  INK, SLATE,  SLATE,  false, IDIOM_DROOP,   25},
  {"shocked",     12,  INK, GOLD,   GOLD,   true,  IDIOM_PERK,    10},
  {"mischievous", 13,  INK, TEAL,   TEAL,   false, IDIOM_SWAY,    20},
  {"unhappy",     14,  INK, SLATE,  SLATE,  false, IDIOM_DROOP,   25},
  {"loving",      15,  INK, ROSE,   ROSE,   true,  IDIOM_BOUNCE,  25},
  {"furious",     16,  INK, EMBER,  EMBER,  true,  IDIOM_SHAKE,   12},
  {"distressed",  17,  INK, EMBER,  EMBER,  true,  IDIOM_MICRO,   15},
  {"laughing",    18,  INK, GOLD,   GOLD,   true,  IDIOM_BOUNCE,  15},
  {"pained",      19,  INK, EMBER,  EMBER,  false, IDIOM_MICRO,   15},
  {"shy",         20,  INK, ROSE,   ROSE,   false, IDIOM_DROOP,   20},
  {"awkward",     21,  INK, PEACH,  PEACH,  false, IDIOM_MICRO,   15},
  {"wailing",     22,  INK, SLATE,  SLATE,  true,  IDIOM_DROOP,   30},
  {"unwell",      23,  INK, MOSS,   MOSS,   false, IDIOM_DROOP,   60},
  {"neutral",     24,  INK, PAPER,  SLATE,  false, IDIOM_STILL,    0},
  {"unimpressed", 25,  INK, PEACH,  PEACH,  false, IDIOM_STILL,   20},
  {"delighted",   26,  INK, GOLD,   GOLD,   true,  IDIOM_DANCE,   20},
  {"anguished",   27,  INK, EMBER,  EMBER,  true,  IDIOM_MICRO,   20},
  {"content",     28,  INK, PEACH,  PEACH,  false, IDIOM_BREATHE, 60},
  {"surprised",   29,  INK, GOLD,   GOLD,   true,  IDIOM_PERK,    10},
  {"yawning",     30,  INK, INDIGO, INDIGO, false, IDIOM_DROOP,   40},
  // Mask 31 is retired: it squints and reads as a squiggle at panel size.
  // The name keeps its slot so every index below it stays put.
  {"gleeful",     26,  INK, GOLD,   GOLD,   true,  IDIOM_BOUNCE,  20},
  {"grumpy",      32,  INK, AMBER,  AMBER,  false, IDIOM_STILL,   30},
  {"playful",     33,  INK, TEAL,   TEAL,   true,  IDIOM_SWAY,    20},
  {"deadpan",     34,  INK, PAPER,  SLATE,  false, IDIOM_STILL,   20},
  {"puzzled",     35,  INK, PEACH,  PEACH,  false, IDIOM_SWAY,    20},
};

// Idiom choreography. Home is 466/620; the measured envelope is yaw 196..737
// and pitch 566..828, and every frame below sits inside it. The firmware
// validates each target again regardless, so this table cannot widen anything.
//
// Speed follows the vendor scale `../Will-Robot` records for this unit: 100
// gentle, 300 quick, 500 snappy. Intensity scales it at runtime, so an emotion
// felt weakly moves gently and the same emotion felt strongly snaps.
struct Keyframe {
  int16_t yaw;
  int16_t pitch;
  uint16_t speed;
  uint16_t settle_ms;
};

constexpr Keyframe FR_MICRO[]   = {{486, 638, 160,  70}, {446, 604, 160,  70},
                                   {480, 632, 160,  70}, {466, 620, 160,   0}};
constexpr Keyframe FR_BREATHE[] = {{466, 704, 130, 150}, {466, 582, 130, 150},
                                   {466, 620, 140,   0}};
constexpr Keyframe FR_PERK[]    = {{466, 776, 500,  90}, {466, 630, 420,   0}};
constexpr Keyframe FR_DROOP[]   = {{466, 572, 160, 300}, {466, 598, 140,   0}};
constexpr Keyframe FR_NOD[]     = {{466, 778, 500,   0}, {466, 574, 500,   0},
                                   {466, 778, 500,   0}, {466, 574, 500,   0},
                                   {466, 620, 460,   0}};
constexpr Keyframe FR_SHAKE[]   = {{286, 620, 500,   0}, {646, 620, 500,   0},
                                   {286, 620, 500,   0}, {646, 620, 500,   0},
                                   {466, 620, 470,   0}};
// Wide and unhurried, leaning into each side like a slow waltz.
constexpr Keyframe FR_SWAY[]    = {{276, 690, 260, 170}, {656, 690, 260, 170},
                                   {366, 646, 280,  90}, {466, 620, 300,   0}};
// Quick pitch beats with a diagonal kick, the way excitement actually moves.
constexpr Keyframe FR_BOUNCE[]  = {{466, 778, 500,   0}, {466, 576, 500,   0},
                                   {580, 778, 500,   0}, {352, 576, 500,   0},
                                   {466, 730, 500,  60}, {466, 620, 450,   0}};
constexpr Keyframe FR_DANCE[]   = {{680, 700, 500,   0}, {252, 700, 500,   0},
                                   {560, 640, 500,   0}, {372, 640, 500,   0},
                                   {520, 640, 500,   0}, {412, 640, 500,   0},
                                   {680, 782, 500,   0}, {252, 572, 500,   0},
                                   {680, 572, 500,   0}, {252, 782, 500,   0},
                                   {466, 782, 500, 140}, {466, 574, 500,   0},
                                   {466, 778, 500,   0}, {520, 660, 500,   0},
                                   {412, 660, 500,   0}, {680, 620, 500,   0},
                                   {252, 620, 500,   0}, {466, 620, 440,   0}};



// Everything below works the full envelope rather than a polite slice of it.
// Yaw reaches 252..680 and pitch 572..782, about 80% of the measured travel on
// each axis. The firmware still validates every target against 196..737 and
// 566..828 and would refuse anything wider.
//
// Travel time is what costs, not speed, so rhythm comes from mixing short beats
// with wide accents rather than running everything at one amplitude.
//
// Gaze keeps its exact calibrated targets: "look right" means thirty degrees
// and the release checks that number.
constexpr Keyframe MP_HOME[]  = {{466, 620, 300, 0}};
constexpr Keyframe MP_LEFT[]  = {{381, 620, 300, 900}, {466, 620, 320, 0}};
constexpr Keyframe MP_RIGHT[] = {{552, 620, 300, 900}, {466, 620, 320, 0}};
constexpr Keyframe MP_UP[]    = {{466, 705, 300, 900}, {466, 620, 320, 0}};
constexpr Keyframe MP_YAW10[]   = {{495, 620, 300, 0}};
constexpr Keyframe MP_PITCH10[] = {{466, 648, 300, 0}};

// Two deep nods through most of the pitch range.
constexpr Keyframe MP_NOD[] = {
  {466, 778, 500, 0}, {466, 574, 500, 0},
  {466, 778, 500, 0}, {466, 574, 500, 0},
  {466, 620, 460, 0},
};

// Wide, fast head shakes.
constexpr Keyframe MP_SHAKE[] = {
  {286, 620, 500, 0}, {646, 620, 500, 0},
  {286, 620, 500, 0}, {646, 620, 500, 0},
  {466, 620, 470, 0},
};

// Down to the bottom of the range, hold, and rise.
constexpr Keyframe MP_BOW[] = {
  {466, 572, 260, 480}, {466, 700, 300, 120}, {466, 620, 320, 0},
};

// Rise, sweep to each side, and level off.
constexpr Keyframe MP_GREET[] = {
  {466, 776, 460, 130}, {620, 730, 460, 90},
  {312, 730, 460, 90},  {466, 680, 420, 70},
  {466, 620, 380, 0},
};

// Fast diagonals across the corners of the envelope.
constexpr Keyframe MP_CELEBRATE[] = {
  {648, 770, 500, 0}, {284, 770, 500, 0},
  {648, 700, 500, 0}, {284, 700, 500, 0},
  {466, 782, 500, 130}, {466, 620, 460, 0},
};

// A slow sweep across nearly the whole yaw range, pausing at each end.
constexpr Keyframe MP_SCAN[] = {
  {252, 660, 190, 340}, {466, 660, 240, 110},
  {680, 660, 190, 340}, {466, 634, 260, 0},
};

// The routine. Wide sweeps and corner diagonals carry the shape, short beats
// carry the rhythm, and it runs long enough to actually read as a dance.
constexpr Keyframe MP_DANCE[] = {
  {680, 700, 500, 0}, {252, 700, 500, 0},
  {560, 640, 500, 0}, {372, 640, 500, 0},
  {520, 640, 500, 0}, {412, 640, 500, 0},
  {520, 640, 500, 0}, {412, 640, 500, 0},
  {680, 782, 500, 0}, {252, 572, 500, 0},
  {680, 572, 500, 0}, {252, 782, 500, 0},
  {466, 782, 500, 140},
  {466, 574, 500, 0}, {466, 778, 500, 0},
  {466, 574, 500, 0}, {466, 778, 500, 0},
  {520, 660, 500, 0}, {412, 660, 500, 0},
  {520, 660, 500, 0}, {412, 660, 500, 0},
  {680, 620, 500, 0}, {252, 620, 500, 0},
  {466, 782, 500, 120}, {466, 620, 440, 0},
};

struct NamedProgram {
  const char *name;
  const Keyframe *frames;
  uint8_t count;
};

#define ANDY_PROGRAM(literal, table) \
  {literal, table, sizeof(table) / sizeof(Keyframe)}

// Order matches the server's MotionAction and the select in `idioms.yaml`.
constexpr NamedProgram MOTION_PROGRAMS[] = {
  ANDY_PROGRAM("home", MP_HOME),
  ANDY_PROGRAM("look_left", MP_LEFT),
  ANDY_PROGRAM("look_right", MP_RIGHT),
  ANDY_PROGRAM("look_up", MP_UP),
  ANDY_PROGRAM("nod_yes", MP_NOD),
  ANDY_PROGRAM("shake_no", MP_SHAKE),
  ANDY_PROGRAM("bow", MP_BOW),
  ANDY_PROGRAM("greet", MP_GREET),
  ANDY_PROGRAM("celebrate", MP_CELEBRATE),
  ANDY_PROGRAM("scan", MP_SCAN),
  ANDY_PROGRAM("dance", MP_DANCE),
  ANDY_PROGRAM("yaw_positive_10", MP_YAW10),
  ANDY_PROGRAM("pitch_positive_10", MP_PITCH10),
};

constexpr uint8_t MOTION_PROGRAM_COUNT =
    sizeof(MOTION_PROGRAMS) / sizeof(NamedProgram);

struct IdiomProgram {
  const Keyframe *frames;
  uint8_t count;
};

// Indexed by Idiom.
constexpr IdiomProgram IDIOM_PROGRAMS[] = {
  {nullptr,     0},                                   // STILL
  {FR_MICRO,    sizeof(FR_MICRO) / sizeof(Keyframe)},
  {FR_BREATHE,  sizeof(FR_BREATHE) / sizeof(Keyframe)},
  {FR_PERK,     sizeof(FR_PERK) / sizeof(Keyframe)},
  {FR_DROOP,    sizeof(FR_DROOP) / sizeof(Keyframe)},
  {FR_NOD,      sizeof(FR_NOD) / sizeof(Keyframe)},
  {FR_SHAKE,    sizeof(FR_SHAKE) / sizeof(Keyframe)},
  {FR_SWAY,     sizeof(FR_SWAY) / sizeof(Keyframe)},
  {FR_BOUNCE,   sizeof(FR_BOUNCE) / sizeof(Keyframe)},
  {FR_DANCE,    sizeof(FR_DANCE) / sizeof(Keyframe)},
};

// Intensity bends speed without ever leaving the documented range.
inline uint16_t scaled_speed(uint16_t base, int intensity) {
  if (intensity < 0) intensity = 0;
  if (intensity > 100) intensity = 100;
  int value = (int)(base * (0.70f + 0.60f * (intensity / 100.0f)));
  if (value < 100) value = 100;
  if (value > 500) value = 500;
  return (uint16_t) value;
}

constexpr uint8_t EMOTION_COUNT = sizeof(EMOTIONS) / sizeof(EMOTIONS[0]);

// Named indices the firmware itself reaches for.
constexpr uint8_t E_NEUTRAL     = 24;
constexpr uint8_t E_SLEEPY      = 2;
constexpr uint8_t E_BLANK       = 3;
constexpr uint8_t E_OVERWHELMED = 4;
constexpr uint8_t E_HAPPY       = 0;
constexpr uint8_t E_LOVING      = 15;
constexpr uint8_t E_SHOCKED     = 12;
constexpr uint8_t E_CONTENT     = 28;
constexpr uint8_t E_SURPRISED   = 29;
constexpr uint8_t E_LAUGHING    = 18;
// The two faces the voice lifecycle wears, chosen for legibility at 220 px on a
// two-inch panel rather than for nuance. `laughing` squints and curves and
// reads as a squiggle from a desk away; `happy` is two round eyes and an open
// mouth, which is unmistakably a face that is speaking. `content` has its eyes
// closed, which reads as asleep when Andy is in fact listening.
constexpr uint8_t E_TALKING     = 0;   // happy: round eyes, open mouth
constexpr uint8_t E_ATTENTIVE   = 24;  // neutral: round eyes, level mouth
constexpr uint8_t E_SAD         = 6;
constexpr uint8_t E_UNWELL      = 23;
constexpr uint8_t E_YAWNING     = 30;

// Precedence. A source may not overwrite a stronger one while it still holds.
constexpr uint8_t P_VOICE    = 0;  // conversation lifecycle
constexpr uint8_t P_AGENT    = 1;  // the server or a person choosing a mood
constexpr uint8_t P_INTERACT = 2;  // being touched, someone arriving
constexpr uint8_t P_DEVICE   = 3;  // muted, offline
constexpr uint8_t P_SAFETY   = 4;  // shaken, faulted

}  // namespace andy
