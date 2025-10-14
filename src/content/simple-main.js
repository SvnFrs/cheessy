// ========================================
// 🚀 OPTIMIZED CHESSY EXTENSION - FIXED VERSION
// ========================================
// Based on working legacy script but with performance improvements
// Fixes: Black/White detection, Continuous analysis, Engine freezing

// 🎯 Simple Logger (Essential for debugging)
class Logger {
  constructor(context = 'ChessyApp') {
    this.context = context;
    this.enabled = true;
  }

  info(...args) {
    if (this.enabled) {
      console.log(`[${this.context}]`, ...args);
    }
  }

  debug(...args) {
    if (this.enabled) {
      console.log(`[${this.context}]`, ...args);
    }
  }

  error(...args) {
    if (this.enabled) {
      console.error(`[${this.context}]`, ...args);
    }
  }
}

// 🚀 Simple Engine (Based on working legacy script)
class SimpleStockfishEngine {
  constructor() {
    this.worker = null;
    this.logger = new Logger('SimpleEngine');
    this.callbacks = {
      analysis: null
    };
  }

  initialize() {
    if (this.worker) {
      this.worker.terminate();
    }
    
    // Simple engine creation (like legacy script)
    this.worker = new Worker("/bundles/app/js/vendor/jschessengine/stockfish.asm.1abfa10c.js");
    this.worker.onmessage = (event) => this.handleMessage(event);
    
    this.logger.info('🚀 Simple engine initialized');
  }

  handleMessage(event) {
    const message = event.data;
    
    if (message.startsWith('bestmove')) {
      const bestMove = message.split(' ')[1];
      this.logger.info('Best move:', bestMove);
      
      if (this.callbacks.analysis) {
        this.callbacks.analysis({
          bestMove,
          evaluation: null,
          depth: null
        });
      }
    }
  }

  onAnalysis(callback) {
    this.callbacks.analysis = callback;
  }

  analyzePosition(fen, depth = 15) {
    if (!this.worker) {
      this.logger.error('Engine not initialized');
      return;
    }

    this.logger.info(`Analyzing position: ${fen} at depth ${depth}`);
    
    // Simple analysis commands (like legacy script)
    this.worker.postMessage(`position fen ${fen}`);
    this.worker.postMessage('go wtime 300000 btime 300000 winc 2000 binc 2000');
    this.worker.postMessage(`go depth ${depth}`);
  }

  terminate() {
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
      this.logger.info('Engine terminated');
    }
  }
}

// 🚀 Simple Chess.com Adapter
class SimpleChessComAdapter {
  constructor() {
    this.logger = new Logger('SimpleAdapter');
    this.currentFen = null;
    this.playerColor = null;
    this.lastBoardState = null;
    this.lastActiveColor = 'w'; // Track last active color for alternation
  }

  // Simple player color detection (like legacy script)
  determinePlayerColor() {
    const chessboard = document.querySelector("wc-chess-board");
    if (!chessboard) {
      this.logger.error('Chessboard not found');
      return null;
    }
    
    // Simple check: if board is flipped, player is black
    const isFlipped = chessboard.classList.contains("flipped");
    this.playerColor = isFlipped ? "b" : "w";
    
    this.logger.info(`Player color: ${this.playerColor === 'w' ? 'White' : 'Black'}`);
    return this.playerColor;
  }

  // Determine whose turn it is (active color) - FIXED VERSION
  determineActiveColor() {
    // Method 1: Count pieces to determine turn (most reliable)
    // In standard chess, after white moves, black has the turn
    // We can check the last move by looking at highlights
    const chessboard = document.querySelector("wc-chess-board");
    
    // Method 2: Check for move highlights (indicates last move)
    // Chess.com adds highlight class to last moved pieces
    const highlights = document.querySelectorAll('.highlight');
    if (highlights.length >= 2) {
      // If we see highlights, the other player should move
      const isFlipped = chessboard?.classList.contains("flipped");
      // This is approximate - better to count moves or check clocks
    }

    // Method 3: Check clock indicators (most reliable on chess.com)
    const bottomClock = document.querySelector('.clock-component.clock-bottom');
    const topClock = document.querySelector('.clock-component.clock-top');
    
    if (bottomClock && topClock) {
      // Clock with 'clock-player-turn' class indicates whose turn it is
      const bottomHasTurn = bottomClock.classList.contains('clock-player-turn') || 
                           bottomClock.querySelector('.clock-player-turn');
      const topHasTurn = topClock.classList.contains('clock-player-turn') || 
                        topClock.querySelector('.clock-player-turn');
      
      const isFlipped = chessboard?.classList.contains("flipped");
      
      if (bottomHasTurn) {
        // Bottom player's turn
        return isFlipped ? 'b' : 'w';
      } else if (topHasTurn) {
        // Top player's turn
        return isFlipped ? 'w' : 'b';
      }
    }

    // Method 4: Fallback - count total moves from pieces
    // If we can't determine, alternate from last known state
    if (this.lastActiveColor) {
      // Alternate the color
      return this.lastActiveColor === 'w' ? 'b' : 'w';
    }

    // Final fallback: white to move (starting position)
    this.logger.debug('Could not determine turn reliably, using fallback');
    return 'w';
  }

  // Simple FEN generation (like legacy script)
  generateFEN() {
    let fen_string = "";
    
    // Generate board position
    for (let i = 8; i >= 1; i--) {
      for (let j = 1; j <= 8; j++) {
        let position = `${j}${i}`;
        
        // Add rank separator
        if (j == 1 && i != 8) {
          fen_string += "/";
        }
        
        let piece_in_position = document.querySelectorAll(`.piece.square-${position}`)[0]?.classList ?? null;
        
        // Get piece name by shortest class (like legacy)
        if (piece_in_position != null) {
          for (let item of piece_in_position.values()) {
            if (item.length == 2) {
              piece_in_position = item;
            }
          }
        }
        
        // Handle empty squares
        if (piece_in_position == null) {
          let previous_char = fen_string.split("").pop();
          if (!isNaN(Number(previous_char))) {
            fen_string = fen_string.substring(0, fen_string.length - 1);
            fen_string += Number(previous_char) + 1;
          } else {
            fen_string += "1";
          }
        }
        // Handle pieces
        else if (piece_in_position?.split("")[0] == "b") {
          fen_string += piece_in_position.split("")[1]; // Black pieces lowercase
        }
        else if (piece_in_position?.split("")[0] == "w") {
          fen_string += piece_in_position.split("")[1].toUpperCase(); // White pieces uppercase
        }
      }
    }
    
    // Add active color
    const activeColor = this.determineActiveColor();
    this.lastActiveColor = activeColor; // Store for next time
    fen_string += ` ${activeColor}`;
    
    this.logger.debug(`Generated FEN: ${fen_string} (active: ${activeColor === 'w' ? 'White' : 'Black'})`);
    return fen_string;
  }

  // Check if board state changed (ignoring active color for position comparison)
  hasBoardChanged() {
    const newFen = this.generateFEN();
    const currentPosition = newFen.split(' ')[0]; // Just the board position
    const lastPosition = this.lastBoardState ? this.lastBoardState.split(' ')[0] : null;
    
    if (lastPosition !== currentPosition) {
      this.logger.info(`Board changed!`);
      this.logger.info(`  Previous: ${this.lastBoardState}`);
      this.logger.info(`  Current:  ${newFen}`);
      this.lastBoardState = newFen;
      return true;
    }
    return false;
  }

  getCurrentFEN() {
    return this.generateFEN();
  }
}

// 🚀 Simple UI Manager
class SimpleUIManager {
  constructor() {
    this.logger = new Logger('SimpleUI');
    this.isActive = false;
  }

  createUI() {
    // Remove existing UI
    this.removeUI();

    const main_body = document.querySelector(".board-layout-main");
    if (!main_body) {
      this.logger.error('Main board layout not found');
      return;
    }

    // Create depth input
    const input = document.createElement("input");
    input.id = "depth-input";
    input.value = 15;
    input.placeholder = "Depth (1-20)";
    input.style.cssText = `
      width: 100%; 
      margin: 5px 0; 
      padding: 8px; 
      border: 1px solid #ccc; 
      border-radius: 4px;
    `;

    // Create main button
    const button = document.createElement("button");
    button.id = "chessy-button";
    button.className = "ui_v5-button-component ui_v5-button-primary ui_v5-button-large ui_v5-button-full";
    button.innerHTML = "🚀 Start Chessy";
    button.style.cssText = `
      margin: 5px 0; 
      padding: 10px; 
      font-weight: bold;
    `;

    // Create status display
    const status = document.createElement("div");
    status.id = "chessy-status";
    status.innerHTML = "Ready to analyze";
    status.style.cssText = `
      margin: 5px 0; 
      padding: 8px; 
      background: #f0f0f0; 
      border-radius: 4px; 
      font-size: 14px;
    `;

    main_body.prepend(status);
    main_body.prepend(button);
    main_body.prepend(input);

    this.logger.info('UI created');
  }

  removeUI() {
    const elements = ['#depth-input', '#chessy-button', '#chessy-status', '.chessy-highlight'];
    elements.forEach(selector => {
      document.querySelectorAll(selector).forEach(el => el.remove());
    });
  }

  updateStatus(message) {
    const status = document.getElementById('chessy-status');
    if (status) {
      status.innerHTML = message;
    }
    this.logger.info(`Status: ${message}`);
  }

  showMove(bestMove) {
    if (!bestMove || bestMove === 'none') return;

    // Remove previous highlights
    document.querySelectorAll('.chessy-highlight').forEach(el => el.remove());

    const chessboard = document.querySelector("wc-chess-board");
    if (!chessboard) return;

    // Parse move (like legacy script)
    const char_map = { "a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7, "h": 8 };
    const move_array = bestMove.split("");
    
    if (move_array.length >= 4) {
      const from_square = `${char_map[move_array[0]]}${move_array[1]}`;
      const to_square = `${char_map[move_array[2]]}${move_array[3]}`;

      // Create highlights
      const from_highlight = document.createElement("div");
      from_highlight.className = `highlight chessy-highlight square-${from_square}`;
      from_highlight.style.cssText = "background: red; opacity: 0.5; z-index: 10;";

      const to_highlight = document.createElement("div");
      to_highlight.className = `highlight chessy-highlight square-${to_square}`;
      to_highlight.style.cssText = "background: red; opacity: 0.5; z-index: 10;";

      chessboard.appendChild(from_highlight);
      chessboard.appendChild(to_highlight);

      this.updateStatus(`🎯 Best move: ${bestMove}`);
    }
  }

  setButtonState(isActive) {
    const button = document.getElementById('chessy-button');
    if (button) {
      if (isActive) {
        button.innerHTML = "⏹️ Stop Chessy";
        button.style.background = "#dc3545";
      } else {
        button.innerHTML = "🚀 Start Chessy";
        button.style.background = "";
      }
    }
    this.isActive = isActive;
  }
}

// 🚀 Main Chess Extension (Simple and Reliable)
class SimpleChessExtension {
  constructor() {
    this.logger = new Logger('ChessExtension');
    this.engine = new SimpleStockfishEngine();
    this.adapter = new SimpleChessComAdapter();
    this.ui = new SimpleUIManager();
    this.isRunning = false;
    this.monitoringInterval = null;
    this.depth = 15;
  }

  async initialize() {
    this.logger.info('🚀 Starting Simple Chess Extension...');
    
    try {
      // Wait for page to load
      await this.waitForBoard();
      
      // Initialize components
      this.engine.initialize();
      this.ui.createUI();
      this.setupEventListeners();
      
      // Setup engine callback
      this.engine.onAnalysis((data) => {
        this.handleAnalysis(data);
      });

      this.logger.info('✅ Extension initialized successfully');
      
    } catch (error) {
      this.logger.error('❌ Failed to initialize:', error);
    }
  }

  async waitForBoard() {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Board not found after 10 seconds'));
      }, 10000);

      const checkBoard = () => {
        const board = document.querySelector("wc-chess-board");
        const main = document.querySelector(".board-layout-main");
        
        if (board && main) {
          clearTimeout(timeout);
          this.logger.info('✅ Board found');
          resolve();
        } else {
          setTimeout(checkBoard, 100);
        }
      };

      checkBoard();
    });
  }

  setupEventListeners() {
    // Button click handler
    document.addEventListener('click', (event) => {
      if (event.target.id === 'chessy-button') {
        if (this.isRunning) {
          this.stop();
        } else {
          this.start();
        }
      }
    });

    // Depth input handler
    document.addEventListener('input', (event) => {
      if (event.target.id === 'depth-input') {
        const value = parseInt(event.target.value);
        if (value >= 1 && value <= 20) {
          this.depth = value;
        }
      }
    });
  }

  start() {
    if (this.isRunning) return;

    this.logger.info('▶️ Starting analysis...');
    this.isRunning = true;
    this.ui.setButtonState(true);
    this.ui.updateStatus('Starting analysis...');

    // Determine player color
    this.adapter.determinePlayerColor();

    // Analyze current position
    this.analyzeCurrentPosition();

    // Start monitoring for changes (like legacy script)
    this.monitoringInterval = setInterval(() => {
      if (this.adapter.hasBoardChanged()) {
        this.analyzeCurrentPosition();
      }
    }, 1000); // Check every second

    this.logger.info('✅ Analysis started');
  }

  stop() {
    if (!this.isRunning) return;

    this.logger.info('⏹️ Stopping analysis...');
    this.isRunning = false;
    this.ui.setButtonState(false);
    this.ui.updateStatus('Analysis stopped');

    // Clear monitoring
    if (this.monitoringInterval) {
      clearInterval(this.monitoringInterval);
      this.monitoringInterval = null;
    }

    // Remove highlights
    document.querySelectorAll('.chessy-highlight').forEach(el => el.remove());

    this.logger.info('✅ Analysis stopped');
  }

  analyzeCurrentPosition() {
    if (!this.isRunning) return;

    try {
      const fen = this.adapter.getCurrentFEN();
      if (!fen) {
        this.logger.error('Could not generate FEN');
        return;
      }

      this.logger.info(`🔍 Analyzing position: ${fen}`);
      this.ui.updateStatus(`Analyzing... (depth ${this.depth})`);
      
      // Start analysis
      this.engine.analyzePosition(fen, this.depth);
      
    } catch (error) {
      this.logger.error('Analysis error:', error);
      this.ui.updateStatus('Analysis error');
    }
  }

  handleAnalysis(data) {
    if (!this.isRunning) return;

    if (data.bestMove && data.bestMove !== 'none') {
      this.logger.info(`✅ Analysis complete: ${data.bestMove}`);
      this.ui.showMove(data.bestMove);
    } else {
      this.ui.updateStatus('No move found');
    }
  }
}

// 🚀 Initialize Extension
let chessExtension = null;

// Wait for page load and initialize
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeExtension);
} else {
  initializeExtension();
}

function initializeExtension() {
  // Avoid multiple initializations
  if (chessExtension) return;

  console.log('🚀 Initializing Simple Chess Extension...');
  
  chessExtension = new SimpleChessExtension();
  chessExtension.initialize().catch(error => {
    console.error('❌ Extension initialization failed:', error);
  });
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
  if (chessExtension) {
    chessExtension.stop();
    chessExtension.engine.terminate();
  }
});

console.log('✅ Simple Chess Extension loaded');