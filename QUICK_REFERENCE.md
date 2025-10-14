# Quick Reference - Chess Extension Turn Handling Fix

## 🎯 The Core Issue

```javascript
// ❌ WRONG - Only suggests for one side
fen += ` ${player_colour}`; // Never changes!

// ✅ CORRECT - Suggests for both sides
fen += ` ${determineActiveColor()}`; // Changes after each move!
```

## 🔑 Key Concept

**Player Color ≠ Active Color**

- **Player Color**: Which side you're controlling (set once at game start)
  - Example: You're playing White
- **Active Color**: Whose turn it is RIGHT NOW (changes every move)
  - Move 1: White's turn
  - Move 2: Black's turn
  - Move 3: White's turn
  - ...and so on

## 📊 The Fix in 3 Steps

### Step 1: Detect Active Color

```javascript
function determineActiveColor() {
  const bottomClock = document.querySelector(".clock-component.clock-bottom");
  const topClock = document.querySelector(".clock-component.clock-top");
  const isFlipped = chessboard.classList.contains("flipped");

  // Check which clock has the turn indicator
  if (bottomClock?.classList.contains("clock-player-turn")) {
    return isFlipped ? "b" : "w"; // Bottom player's turn
  } else if (topClock?.classList.contains("clock-player-turn")) {
    return isFlipped ? "w" : "b"; // Top player's turn
  }

  // Fallback: alternate
  return lastActiveColor === "w" ? "b" : "w";
}
```

### Step 2: Use Active Color in FEN

```javascript
// Generate board position
let fen_string = getFenString();

// Add ACTIVE color (not player color!)
let active_color = determineActiveColor();
fen_string += ` ${active_color}`;

// Now Stockfish knows whose turn it is
engine.postMessage(`position fen ${fen_string}`);
```

### Step 3: Monitor Changes

```javascript
// Check for board changes every second
setInterval(() => {
  let new_fen = getFenString();
  let new_active = determineActiveColor(); // Get current turn
  new_fen += ` ${new_active}`;

  if (new_fen !== old_fen) {
    // Board changed! Analyze new position
    engine.postMessage(`position fen ${new_fen}`);
    engine.postMessage(`go depth ${depth}`);
  }
}, 1000);
```

## 🎮 Board Orientation

### Normal Board (Playing as White)

```
Rank 8: ♜ ♞ ♝ ♛ ♚ ♝ ♞ ♜  ← Black (Top)
Rank 7: ♟ ♟ ♟ ♟ ♟ ♟ ♟ ♟
...
Rank 2: ♙ ♙ ♙ ♙ ♙ ♙ ♙ ♙
Rank 1: ♖ ♘ ♗ ♕ ♔ ♗ ♘ ♖  ← White (Bottom)

Bottom turn → White to move
Top turn → Black to move
```

### Flipped Board (Playing as Black)

```
Rank 1: ♖ ♘ ♗ ♕ ♔ ♗ ♘ ♖  ← White (Top)
Rank 2: ♙ ♙ ♙ ♙ ♙ ♙ ♙ ♙
...
Rank 7: ♟ ♟ ♟ ♟ ♟ ♟ ♟ ♟
Rank 8: ♜ ♞ ♝ ♛ ♚ ♝ ♞ ♜  ← Black (Bottom)

Bottom turn → Black to move
Top turn → White to move
```

## 🔍 Testing Checklist

### As White Player:

- [x] Extension starts
- [x] Suggests move for White (your turn)
- [x] You make move
- [x] Extension suggests move for Black (opponent's turn)
- [x] Opponent moves
- [x] Extension suggests move for White again
- [x] Continues throughout game

### As Black Player:

- [x] Extension starts
- [x] Opponent moves first
- [x] Extension suggests move for Black (your turn)
- [x] You make move
- [x] Extension suggests move for White (opponent's turn)
- [x] Opponent moves
- [x] Extension suggests move for Black again
- [x] Continues throughout game

## 📝 Console Log Examples

### Correct Behavior:

```
Generated FEN: rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w (White to move)
Best move: e2e4

// After White plays e2e4:
Board changed!
Generated FEN: rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b (Black to move)
Best move: e7e5

// After Black plays e7e5:
Board changed!
Generated FEN: rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w (White to move)
Best move: g1f3
```

### Incorrect Behavior (OLD BUG):

```
Generated FEN: rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w (White to move)
Best move: e2e4

// After White plays e2e4:
Board changed!
Generated FEN: rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w (STILL White?!)
Best move: (no move - position is illegal)
```

## 🎯 Key Points

1. **Always use `determineActiveColor()`** - Not player color
2. **Check clock indicators** - Most reliable method
3. **Handle board flipping** - Important for Black perspective
4. **Monitor continuously** - Check for changes every second
5. **Update FEN properly** - Include correct active color

## 🚀 Files Modified

| File                     | What Changed                                      |
| ------------------------ | ------------------------------------------------- |
| `simple-main.js`         | Enhanced `determineActiveColor()`, added tracking |
| `main.js`                | Added `getActiveColor()` to adapter, updated FEN  |
| `scripts-legacy/main.js` | Added `determineActiveColor()` function           |

## ✅ Result

**The extension now works perfectly for both sides:**

- ✅ White and Black both get suggestions
- ✅ Updates after every move
- ✅ Works with flipped boards
- ✅ Continuous analysis
- ✅ Reliable turn detection

---

**Last Updated:** October 14, 2025
**Status:** ✅ Fixed and Working
