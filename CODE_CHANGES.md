# Code Changes Summary

## 🎯 Overview

Fixed all 3 versions of the chess extension to properly handle turn detection for both Black and White pieces.

---

## 📁 File 1: `src/content/simple-main.js` (Currently Active)

### Change 1: Added `lastActiveColor` tracking

**Location:** Line ~94 in SimpleChessComAdapter constructor

```diff
  constructor() {
    this.logger = new Logger('SimpleAdapter');
    this.currentFen = null;
    this.playerColor = null;
    this.lastBoardState = null;
+   this.lastActiveColor = 'w'; // Track last active color for alternation
  }
```

### Change 2: Enhanced `determineActiveColor()` method

**Location:** Line ~112-150

```diff
- // Determine whose turn it is (active color)
- determineActiveColor() {
-   // Method 1: Check turn indicators in UI
-   const turnIndicators = [
-     '.clock-player-turn',
-     '.clock-component.clock-bottom.clock-player-turn',
-     '.clock-component.clock-top.clock-player-turn',
-     '[class*="turn"]',
-     '.player-turn'
-   ];
-
-   for (const selector of turnIndicators) {
-     const element = document.querySelector(selector);
-     if (element) {
-       // Check if bottom player (usually white) has turn
-       const isBottomTurn = element.closest('.clock-bottom') !== null;
-       const activeColor = isBottomTurn ? 'w' : 'b';
-       this.logger.debug(`Turn indicator found: ${selector}, active: ${activeColor}`);
-       return activeColor;
-     }
-   }
-
-   // Method 2: Check if it's player's turn
-   const chessboard = document.querySelector("wc-chess-board");
-   if (chessboard) {
-     const isFlipped = chessboard.classList.contains("flipped");
-
-     // If board is flipped, bottom is black, top is white
-     // If board is normal, bottom is white, top is black
-     const moveInput = document.querySelector('input[data-cy="move-input"]');
-     if (moveInput && !moveInput.disabled) {
-       // If move input is enabled, it's player's turn
-       return isFlipped ? 'b' : 'w';
-     }
-   }
-
-   // Default: assume white to move (standard starting position)
-   this.logger.debug('Could not determine turn, defaulting to white');
-   return 'w';
- }

+ // Determine whose turn it is (active color) - FIXED VERSION
+ determineActiveColor() {
+   const chessboard = document.querySelector("wc-chess-board");
+
+   // Check clock indicators (most reliable on chess.com)
+   const bottomClock = document.querySelector('.clock-component.clock-bottom');
+   const topClock = document.querySelector('.clock-component.clock-top');
+
+   if (bottomClock && topClock) {
+     // Clock with 'clock-player-turn' class indicates whose turn it is
+     const bottomHasTurn = bottomClock.classList.contains('clock-player-turn') ||
+                          bottomClock.querySelector('.clock-player-turn');
+     const topHasTurn = topClock.classList.contains('clock-player-turn') ||
+                       topClock.querySelector('.clock-player-turn');
+
+     const isFlipped = chessboard?.classList.contains("flipped");
+
+     if (bottomHasTurn) {
+       // Bottom player's turn
+       return isFlipped ? 'b' : 'w';
+     } else if (topHasTurn) {
+       // Top player's turn
+       return isFlipped ? 'w' : 'b';
+     }
+   }
+
+   // Fallback - alternate from last known state
+   if (this.lastActiveColor) {
+     // Alternate the color
+     return this.lastActiveColor === 'w' ? 'b' : 'w';
+   }
+
+   // Final fallback: white to move (starting position)
+   this.logger.debug('Could not determine turn reliably, using fallback');
+   return 'w';
+ }
```

### Change 3: Store active color in FEN generation

**Location:** Line ~210-215

```diff
    // Add active color
    const activeColor = this.determineActiveColor();
+   this.lastActiveColor = activeColor; // Store for next time
    fen_string += ` ${activeColor}`;

-   this.logger.debug(`Generated FEN: ${fen_string}`);
+   this.logger.debug(`Generated FEN: ${fen_string} (active: ${activeColor === 'w' ? 'White' : 'Black'})`);
    return fen_string;
```

### Change 4: Improved board change detection

**Location:** Line ~218-227

```diff
- // Check if board state changed
- hasBoardChanged() {
-   const newFen = this.generateFEN();
-   if (this.lastBoardState !== newFen) {
-     this.logger.info(`Board changed: ${this.lastBoardState} -> ${newFen}`);
-     this.lastBoardState = newFen;
-     return true;
-   }
-   return false;
- }

+ // Check if board state changed (ignoring active color for position comparison)
+ hasBoardChanged() {
+   const newFen = this.generateFEN();
+   const currentPosition = newFen.split(' ')[0]; // Just the board position
+   const lastPosition = this.lastBoardState ? this.lastBoardState.split(' ')[0] : null;
+
+   if (lastPosition !== currentPosition) {
+     this.logger.info(`Board changed!`);
+     this.logger.info(`  Previous: ${this.lastBoardState}`);
+     this.logger.info(`  Current:  ${newFen}`);
+     this.lastBoardState = newFen;
+     return true;
+   }
+   return false;
+ }
```

---

## 📁 File 2: `scripts-legacy/main.js`

### Change 1: Added active color tracking and detection function

**Location:** Line ~5-35

```diff
  function main() {
    const chessboard = document.querySelector("wc-chess-board");
    var player_colour = chessboard.classList.contains("flipped") ? "b" : "w";
+   var last_active_color = "w"; // Track whose turn it is
+
+   // Function to determine whose turn it is (active color)
+   function determineActiveColor() {
+     // Check clock indicators
+     const bottomClock = document.querySelector('.clock-component.clock-bottom');
+     const topClock = document.querySelector('.clock-component.clock-top');
+     const isFlipped = chessboard.classList.contains("flipped");
+
+     if (bottomClock && topClock) {
+       const bottomHasTurn = bottomClock.classList.contains('clock-player-turn');
+       const topHasTurn = topClock.classList.contains('clock-player-turn');
+
+       if (bottomHasTurn) {
+         last_active_color = isFlipped ? 'b' : 'w';
+         return last_active_color;
+       } else if (topHasTurn) {
+         last_active_color = isFlipped ? 'w' : 'b';
+         return last_active_color;
+       }
+     }
+
+     // Fallback: alternate colors
+     last_active_color = (last_active_color === 'w') ? 'b' : 'w';
+     return last_active_color;
+   }
+
    //generate FEN string from board,
    function getFenString() {
```

### Change 2: Use active color in initial FEN

**Location:** Line ~65-70

```diff
    }
    return fen_string
  }
  let fen_string = getFenString()
- fen_string += ` ${player_colour}`
+ let active_color = determineActiveColor(); // Get whose turn it is
+ fen_string += ` ${active_color}`
  console.log(fen_string)
```

### Change 3: Update active color on each move

**Location:** Line ~75-85

```diff
  //listen for when moves are made
  var getPlays = setInterval(() => {
    let new_fen_string = getFenString()
-   new_fen_string += ` ${player_colour}`
+   let new_active_color = determineActiveColor(); // Get whose turn it is NOW
+   new_fen_string += ` ${new_active_color}`
    if (new_fen_string != fen_string) {
      fen_string = new_fen_string
+     console.log(`New position: ${fen_string} (${new_active_color === 'w' ? 'White' : 'Black'} to move)`);
      engine.postMessage(`position fen ${fen_string}`)
      engine.postMessage('go wtime 300000 btime 300000 winc 2000 binc 2000');
      console.log(globalDepth);
-     engine.postMessage("go depth ${globalDepth}")
+     engine.postMessage(`go depth ${globalDepth}`)
    }
- })
+ }, 1000)
```

---

## 📁 File 3: `src/content/main.js`

### Change 1: Added active color tracking to ChessComAdapter

**Location:** Line ~70-75

```diff
  class ChessComAdapter {
    constructor() {
      this.boardElement = null;
      this.observers = [];
      this.logger = new Logger('ChessComAdapter');
+     this.lastActiveColor = 'w'; // Track active color
    }
```

### Change 2: Added `getActiveColor()` method

**Location:** Line ~87-110

```diff
    getPlayerColor() {
      const board = this.getBoardElement();
      return board?.classList.contains('flipped') ? 'black' : 'white';
    }
+
+   // Determine whose turn it is (active color)
+   getActiveColor() {
+     const board = this.getBoardElement();
+     const isFlipped = board?.classList.contains('flipped');
+
+     // Check clock indicators
+     const bottomClock = document.querySelector('.clock-component.clock-bottom');
+     const topClock = document.querySelector('.clock-component.clock-top');
+
+     if (bottomClock && topClock) {
+       const bottomHasTurn = bottomClock.classList.contains('clock-player-turn');
+       const topHasTurn = topClock.classList.contains('clock-player-turn');
+
+       if (bottomHasTurn) {
+         this.lastActiveColor = isFlipped ? 'b' : 'w';
+         return this.lastActiveColor;
+       } else if (topHasTurn) {
+         this.lastActiveColor = isFlipped ? 'w' : 'b';
+         return this.lastActiveColor;
+       }
+     }
+
+     // Fallback: alternate colors
+     this.lastActiveColor = (this.lastActiveColor === 'w') ? 'b' : 'w';
+     return this.lastActiveColor;
+   }
```

### Change 3: Use active color in FEN generation

**Location:** Line ~245-270

```diff
    generate() {
      const positions = this.siteAdapter.getPiecePositions();
-     const playerColor = this.siteAdapter.getPlayerColor();
+     const activeColor = this.siteAdapter.getActiveColor(); // Get whose turn it is

      this.logger.info('Piece positions:', positions);

      let fen = '';

      // Generate board position (rank 8 to rank 1)
      for (let rank = 8; rank >= 1; rank--) {
        // ... (board generation code unchanged)
      }

-     // Add active color
-     const activeColor = playerColor === 'white' ? 'w' : 'b';
-     fen += ` ${activeColor}`;
+     // Add active color (whose turn it is)
+     fen += ` ${activeColor}`;

      // Add castling rights, en passant, and move clocks
      fen += ' KQkq - 0 1';

-     this.logger.info('Generated FEN:', fen);
+     this.logger.info('Generated FEN:', fen, `(${activeColor === 'w' ? 'White' : 'Black'} to move)`);
      return fen;
    }
```

---

## 🎯 Summary of Changes

### All 3 Files:

1. ✅ Added function to detect **active color** (whose turn it is)
2. ✅ Uses Chess.com's clock indicators for reliable detection
3. ✅ Handles board flipping (playing as Black)
4. ✅ Has fallback mechanism (alternates colors)
5. ✅ Updates FEN string with correct active color
6. ✅ Enhanced logging for debugging

### Key Difference:

```javascript
// BEFORE (Wrong):
fen += ` ${player_colour}`; // Only detects once, never changes

// AFTER (Correct):
fen += ` ${determineActiveColor()}`; // Detects on every move
```

---

## 🚀 Impact

- ✅ Extension now works for **both Black and White**
- ✅ Suggests moves for **both sides** throughout the game
- ✅ **Continuous analysis** after each move
- ✅ Properly handles **board orientation**
- ✅ More **reliable turn detection**

---

**Date:** October 14, 2025  
**Status:** ✅ All fixes applied and tested
