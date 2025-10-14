class Logger {
  constructor(context = 'Cheessy') {
    this.context = context;
  }

  log(level, message, ...args) {
    console[level](`[${this.context}] ${message}`, ...args);
  }

  info(message, ...args) {
    this.log('info', message, ...args);
  }

  warn(message, ...args) {
    this.log('warn', message, ...args);
  }

  error(message, ...args) {
    this.log('error', message, ...args);
  }
}

class EventEmitter {
  constructor() {
    this.events = {};
  }

  on(event, callback) {
    if (!this.events[event]) {
      this.events[event] = [];
    }
    this.events[event].push(callback);
  }

  emit(event, ...args) {
    if (!this.events[event]) return;

    this.events[event].forEach(callback => {
      try {
        callback(...args);
      } catch (error) {
        console.error('Event callback error:', error);
      }
    });
  }
}

class Config {
  constructor() {
    this.defaults = {
      depth: 15,
      engine: 'stockfish',
      timeLimit: 5000
    };
  }

  get(key, defaultValue = null) {
    return this.defaults[key] || defaultValue;
  }

  set(key, value) {
    this.defaults[key] = value;
  }
}

// Fixed ChessComAdapter with proper coordinate conversion
class ChessComAdapter {
  constructor() {
    this.boardElement = null;
    this.observers = [];
    this.logger = new Logger('ChessComAdapter');
    this.lastActiveColor = 'w'; // Track active color
  }

  isSupported() {
    return window.location.hostname.includes('chess.com');
  }

  getBoardElement() {
    this.boardElement = document.querySelector('wc-chess-board, chess-board');
    return this.boardElement;
  }

  getPlayerColor() {
    const board = this.getBoardElement();
    return board?.classList.contains('flipped') ? 'black' : 'white';
  }

  // Determine whose turn it is (active color)
  getActiveColor() {
    const board = this.getBoardElement();
    const isFlipped = board?.classList.contains('flipped');
    
    // Check clock indicators
    const bottomClock = document.querySelector('.clock-component.clock-bottom');
    const topClock = document.querySelector('.clock-component.clock-top');
    
    if (bottomClock && topClock) {
      const bottomHasTurn = bottomClock.classList.contains('clock-player-turn');
      const topHasTurn = topClock.classList.contains('clock-player-turn');
      
      if (bottomHasTurn) {
        this.lastActiveColor = isFlipped ? 'b' : 'w';
        return this.lastActiveColor;
      } else if (topHasTurn) {
        this.lastActiveColor = isFlipped ? 'w' : 'b';
        return this.lastActiveColor;
      }
    }
    
    // Fallback: alternate colors
    this.lastActiveColor = (this.lastActiveColor === 'w') ? 'b' : 'w';
    return this.lastActiveColor;
  }

  observeBoardChanges(callback) {
    const board = this.getBoardElement();
    if (!board) return;

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'childList' ||
            (mutation.type === 'attributes' && mutation.attributeName === 'class')) {
          callback();
          break;
        }
      }
    });

    observer.observe(board, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class']
    });

    this.observers.push(observer);
  }

  highlightMove(fromSquare, toSquare) {
    this.clearHighlights();

    const board = this.getBoardElement();
    if (!board) {
      this.logger.warn('Board element not found');
      return;
    }

    // Convert algebraic notation (e.g., "e2") to chess.com's coordinate system
    const fromCoords = this.convertAlgebraicToCoords(fromSquare);
    const toCoords = this.convertAlgebraicToCoords(toSquare);

    this.logger.info(`Highlighting move: ${fromSquare} (${fromCoords}) -> ${toSquare} (${toCoords})`);

    [fromCoords, toCoords].forEach((coords, index) => {
      if (coords) {
        const highlight = document.createElement('div');
        highlight.className = `highlight cheessy-highlight square-${coords}`;
        highlight.style.cssText = `
          position: absolute !important;
          background: ${index === 0 ? 'rgba(255, 255, 0, 0.7)' : 'rgba(255, 0, 0, 0.7)'} !important;
          pointer-events: none !important;
          z-index: 100 !important;
          border: 2px solid ${index === 0 ? '#ffff00' : '#ff0000'} !important;
          box-sizing: border-box !important;
          border-radius: 4px !important;
        `;
        board.appendChild(highlight);
      }
    });
  }

  convertAlgebraicToCoords(square) {
    if (!square || square.length < 2) return null;

    // Convert algebraic notation (e.g., "e2") to chess.com coordinates (e.g., "52")
    const fileMap = { 'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6, 'g': 7, 'h': 8 };
    const file = square[0].toLowerCase();
    const rank = square[1];

    if (fileMap[file] && rank >= '1' && rank <= '8') {
      return `${fileMap[file]}${rank}`;
    }

    return null;
  }

  clearHighlights() {
    document.querySelectorAll('.cheessy-highlight').forEach(el => el.remove());
  }

  getPiecePositions() {
    const positions = {};
    const pieces = document.querySelectorAll('.piece');

    pieces.forEach(piece => {
      const classes = Array.from(piece.classList);
      const squareClass = classes.find(cls => cls.startsWith('square-'));
      const pieceClass = classes.find(cls => cls.length === 2 && /^[wb][prnbqk]$/.test(cls));

      if (squareClass && pieceClass) {
        // Convert from chess.com coordinates (e.g., "52") back to algebraic (e.g., "e2")
        const coords = squareClass.replace('square-', '');
        const square = this.convertCoordsToAlgebraic(coords);
        if (square) {
          positions[square] = pieceClass;
        }
      }
    });

    return positions;
  }

  convertCoordsToAlgebraic(coords) {
    if (!coords || coords.length !== 2) return null;

    const fileMap = { '1': 'a', '2': 'b', '3': 'c', '4': 'd', '5': 'e', '6': 'f', '7': 'g', '8': 'h' };
    const file = coords[0];
    const rank = coords[1];

    if (fileMap[file] && rank >= '1' && rank <= '8') {
      return `${fileMap[file]}${rank}`;
    }

    return null;
  }

  destroy() {
    this.observers.forEach(observer => observer.disconnect());
    this.observers = [];
    this.clearHighlights();
  }
}

// Fixed FenGenerator with proper coordinate conversion
class FenGenerator {
  constructor(siteAdapter) {
    this.siteAdapter = siteAdapter;
    this.logger = new Logger('FenGenerator');
  }

  generate() {
    const positions = this.siteAdapter.getPiecePositions();
    const activeColor = this.siteAdapter.getActiveColor(); // Get whose turn it is

    this.logger.info('Piece positions:', positions);

    let fen = '';

    // Generate board position (rank 8 to rank 1)
    for (let rank = 8; rank >= 1; rank--) {
      let emptySquares = 0;

      // Files a-h (columns 1-8)
      for (let file = 1; file <= 8; file++) {
        const square = this.getAlgebraicNotation(file, rank);
        const piece = positions[square];

        if (piece) {
          if (emptySquares > 0) {
            fen += emptySquares;
            emptySquares = 0;
          }
          fen += this.convertPieceNotation(piece);
        } else {
          emptySquares++;
        }
      }

      if (emptySquares > 0) {
        fen += emptySquares;
      }

      if (rank > 1) {
        fen += '/';
      }
    }

    // Add active color (whose turn it is)
    fen += ` ${activeColor}`;

    // Add castling rights, en passant, and move clocks
    fen += ' KQkq - 0 1';

    this.logger.info('Generated FEN:', fen, `(${activeColor === 'w' ? 'White' : 'Black'} to move)`);
    return fen;
  }

  getAlgebraicNotation(file, rank) {
    const files = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
    return `${files[file - 1]}${rank}`;
  }

  convertPieceNotation(piece) {
    if (piece.length !== 2) return '';

    const [color, type] = piece;
    return color === 'w' ? type.toUpperCase() : type.toLowerCase();
  }
}

// Stockfish Engine (unchanged)
class StockfishEngine {
  constructor() {
    this.isReady = false;
    this.currentPosition = null;
    this.analysisCallback = null;
    this.worker = null;
    this.logger = new Logger('StockfishEngine');
  }

  async initialize() {
    try {
      const stockfishPath = "/bundles/app/js/vendor/jschessengine/stockfish.asm.1abfa10c.js";
      this.worker = new Worker(stockfishPath);

      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('Engine initialization timeout'));
        }, 10000);

        this.worker.onmessage = (event) => {
          const message = event.data;

          if (message.includes('Stockfish') || message.includes('readyok') || message.includes('uciok')) {
            clearTimeout(timeout);
            this.isReady = true;
            this.setupMessageHandler();
            resolve();
          }
        };

        this.worker.postMessage('uci');
        this.worker.postMessage('isready');
      });
    } catch (error) {
      this.logger.error('Failed to initialize engine:', error);
      throw error;
    }
  }

  setupMessageHandler() {
    this.worker.onmessage = (event) => {
      const message = event.data;

      if (message.startsWith('bestmove')) {
        this.handleBestMove(message);
      } else if (message.startsWith('info')) {
        this.handleAnalysisInfo(message);
      }
    };
  }

  handleBestMove(message) {
    const parts = message.split(' ');
    const bestMove = parts[1];

    if (this.analysisCallback && bestMove !== '(none)') {
      this.analysisCallback({
        type: 'bestmove',
        move: bestMove,
        ponder: parts[3] || null
      });
    }
  }

  handleAnalysisInfo(message) {
    const info = this.parseInfoMessage(message);
    if (this.analysisCallback && (info.score !== undefined || info.mate !== undefined)) {
      this.analysisCallback({
        type: 'analysis',
        ...info
      });
    }
  }

  parseInfoMessage(message) {
    const parts = message.split(' ');
    const info = {};

    for (let i = 0; i < parts.length; i++) {
      switch (parts[i]) {
        case 'depth':
          info.depth = parseInt(parts[i + 1]);
          break;
        case 'score':
          if (parts[i + 1] === 'cp') {
            info.score = parseInt(parts[i + 2]) / 100;
          } else if (parts[i + 1] === 'mate') {
            info.mate = parseInt(parts[i + 2]);
          }
          break;
        case 'pv':
          info.principalVariation = parts.slice(i + 1);
          break;
      }
    }

    return info;
  }

  async setPosition(fen) {
    if (!this.isReady) {
      throw new Error('Engine not ready');
    }

    this.currentPosition = fen;
    this.worker.postMessage(`position fen ${fen}`);
  }

  async analyze(depth = 15, timeLimit = 5000) {
    if (!this.isReady || !this.currentPosition) {
      throw new Error('Engine not ready or position not set');
    }

    this.worker.postMessage(`go depth ${depth} movetime ${timeLimit}`);
  }

  stop() {
    if (this.worker) {
      this.worker.postMessage('stop');
    }
  }

  onAnalysis(callback) {
    this.analysisCallback = callback;
  }

  destroy() {
    this.stop();
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
    this.isReady = false;
  }
}

// UI Component (unchanged)
class ChessyUI extends EventEmitter {
  constructor() {
    super();
    this.container = null;
    this.isVisible = true;
  }

  create() {
    this.container = document.createElement('div');
    this.container.className = 'cheessy-container';
    this.container.innerHTML = this.getTemplate();

    this.attachEventListeners();
    this.insertIntoPage();
  }

  getTemplate() {
    return `
      <div class="cheessy-panel">
        <div class="cheessy-header">
          <h3>Cheessy Analysis</h3>
          <button class="cheessy-toggle" id="cheessy-toggle">−</button>
        </div>
        <div class="cheessy-content" id="cheessy-content" style="display: block;">
          <div class="cheessy-controls">
            <label>
              Depth:
              <input type="number" id="cheessy-depth" value="15" min="1" max="25">
            </label>
            <button id="cheessy-start" class="cheessy-btn-primary">Start Analysis</button>
            <button id="cheessy-stop" class="cheessy-btn-secondary" disabled>Stop</button>
          </div>
          <div class="cheessy-analysis" id="cheessy-analysis">
            <div class="cheessy-bestmove">Best move: <span id="cheessy-bestmove">-</span></div>
            <div class="cheessy-evaluation">Evaluation: <span id="cheessy-eval">-</span></div>
            <div class="cheessy-depth-display">Depth: <span id="cheessy-current-depth">-</span></div>
          </div>
        </div>
      </div>
    `;
  }

  attachEventListeners() {
    const toggle = this.container.querySelector('#cheessy-toggle');
    const startBtn = this.container.querySelector('#cheessy-start');
    const stopBtn = this.container.querySelector('#cheessy-stop');
    const depthInput = this.container.querySelector('#cheessy-depth');

    toggle.addEventListener('click', () => this.toggle());
    startBtn.addEventListener('click', () => this.emit('start', {
      depth: parseInt(depthInput.value)
    }));
    stopBtn.addEventListener('click', () => this.emit('stop'));

    depthInput.addEventListener('change', (e) =>
      this.emit('depthChange', parseInt(e.target.value)));
  }

  insertIntoPage() {
    if (!document.getElementById('cheessy-styles')) {
      const style = document.createElement('style');
      style.id = 'cheessy-styles';
      style.textContent = `
        .cheessy-container {
          position: fixed;
          top: 10px;
          right: 10px;
          background: #2c2c2c;
          color: white;
          border-radius: 8px;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
          font-family: Arial, sans-serif;
          font-size: 14px;
          z-index: 10000;
          max-width: 300px;
          min-width: 250px;
        }

        .cheessy-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 16px;
          border-bottom: 1px solid #444;
          background: #333;
          border-radius: 8px 8px 0 0;
        }

        .cheessy-header h3 {
          margin: 0;
          font-size: 16px;
          font-weight: bold;
        }

        .cheessy-toggle {
          background: #007bff;
          color: white;
          border: none;
          padding: 4px 8px;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
          font-weight: bold;
          min-width: 24px;
        }

        .cheessy-toggle:hover {
          background: #0056b3;
        }

        .cheessy-content {
          padding: 16px;
        }

        .cheessy-controls {
          margin-bottom: 16px;
        }

        .cheessy-controls label {
          display: block;
          margin-bottom: 12px;
          font-weight: bold;
        }

        .cheessy-controls input {
          width: 100%;
          padding: 6px 8px;
          margin-top: 4px;
          border: 1px solid #555;
          border-radius: 4px;
          background: #3c3c3c;
          color: white;
          box-sizing: border-box;
        }

        .cheessy-btn-primary,
        .cheessy-btn-secondary {
          padding: 8px 16px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          margin-right: 8px;
          margin-top: 8px;
          font-weight: bold;
        }

        .cheessy-btn-primary {
          background: #28a745;
          color: white;
        }

        .cheessy-btn-primary:hover:not(:disabled) {
          background: #218838;
        }

        .cheessy-btn-secondary {
          background: #dc3545;
          color: white;
        }

        .cheessy-btn-secondary:hover:not(:disabled) {
          background: #c82333;
        }

        .cheessy-btn-primary:disabled,
        .cheessy-btn-secondary:disabled {
          background: #666;
          cursor: not-allowed;
        }

        .cheessy-analysis div {
          margin-bottom: 6px;
          padding: 4px 0;
        }

        .cheessy-bestmove, .cheessy-evaluation, .cheessy-depth-display {
          font-weight: bold;
        }
      `;
      document.head.appendChild(style);
    }

    const target = document.querySelector('.board-layout-main') ||
                   document.querySelector('.main-board') ||
                   document.body;
    target.appendChild(this.container);
  }

  toggle() {
    const content = this.container.querySelector('#cheessy-content');
    const toggle = this.container.querySelector('#cheessy-toggle');
    this.isVisible = !this.isVisible;
    content.style.display = this.isVisible ? 'block' : 'none';
    toggle.textContent = this.isVisible ? '−' : '+';
  }

  updateAnalysis({ bestmove, evaluation, depth, mate }) {
    if (bestmove) {
      this.container.querySelector('#cheessy-bestmove').textContent = bestmove;
    }
    if (evaluation !== undefined) {
      this.container.querySelector('#cheessy-eval').textContent = evaluation.toFixed(2);
    }
    if (mate !== undefined) {
      this.container.querySelector('#cheessy-eval').textContent = `Mate in ${mate}`;
    }
    if (depth !== undefined) {
      this.container.querySelector('#cheessy-current-depth').textContent = depth;
    }
  }

  setAnalysisState(isRunning) {
    const startBtn = this.container.querySelector('#cheessy-start');
    const stopBtn = this.container.querySelector('#cheessy-stop');

    startBtn.disabled = isRunning;
    stopBtn.disabled = !isRunning;

    if (isRunning) {
      startBtn.textContent = 'Analyzing...';
    } else {
      startBtn.textContent = 'Start Analysis';
    }
  }

  destroy() {
    if (this.container && this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
  }
}

// Main Application (unchanged except for better logging)
class ChessyApp {
  constructor() {
    this.engine = null;
    this.siteAdapter = null;
    this.fenGenerator = null;
    this.ui = null;
    this.logger = new Logger('ChessyApp');
    this.config = new Config();
    this.isAnalyzing = false;
    this.currentFen = null;
    this.boardChangeTimeout = null;
  }

  async initialize() {
    try {
      this.logger.info('Initializing Cheessy...');

      this.siteAdapter = new ChessComAdapter();

      if (!this.siteAdapter.isSupported()) {
        this.logger.warn('Current site not supported');
        return;
      }

      await this.waitForBoard();

      this.fenGenerator = new FenGenerator(this.siteAdapter);
      this.ui = new ChessyUI();

      this.ui.create();
      this.setupUIEventListeners();

      this.siteAdapter.observeBoardChanges(() => this.onBoardChange());

      this.logger.info('Cheessy initialized successfully');
    } catch (error) {
      this.logger.error('Failed to initialize:', error);
    }
  }

  async waitForBoard() {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Board not found within timeout'));
      }, 15000);

      const checkBoard = () => {
        if (this.siteAdapter.getBoardElement()) {
          clearTimeout(timeout);
          this.logger.info('Board found');
          resolve();
        } else {
          setTimeout(checkBoard, 500);
        }
      };

      checkBoard();
    });
  }

  setupUIEventListeners() {
    this.ui.on('start', async (options) => {
      await this.startAnalysis(options);
    });

    this.ui.on('stop', () => {
      this.stopAnalysis();
    });

    this.ui.on('depthChange', (depth) => {
      this.config.set('depth', depth);
    });
  }

  async startAnalysis(options = {}) {
    if (this.isAnalyzing) return;

    try {
      this.isAnalyzing = true;
      this.ui.setAnalysisState(true);
      this.logger.info('Starting analysis...');

      if (!this.engine) {
        this.engine = new StockfishEngine();
        await this.engine.initialize();

        this.engine.onAnalysis((data) => {
          this.handleEngineAnalysis(data);
        });
      }

      await this.analyzeCurrentPosition(options);
    } catch (error) {
      this.logger.error('Failed to start analysis:', error);
      this.stopAnalysis();
      alert('Failed to start analysis: ' + error.message);
    }
  }

  stopAnalysis() {
    this.isAnalyzing = false;
    this.ui.setAnalysisState(false);
    this.siteAdapter.clearHighlights();

    if (this.engine) {
      this.engine.stop();
    }

    this.logger.info('Analysis stopped');
  }

  async analyzeCurrentPosition(options = {}) {
    if (!this.isAnalyzing) return;

    try {
      const fen = this.fenGenerator.generate();

      if (fen !== this.currentFen) {
        this.currentFen = fen;
        await this.engine.setPosition(fen);
        await this.engine.analyze(
          options.depth || this.config.get('depth', 15),
          options.timeLimit || 5000
        );
      }
    } catch (error) {
      this.logger.error('Analysis error:', error);
    }
  }

  handleEngineAnalysis(data) {
    if (!this.isAnalyzing) return;

    if (data.type === 'bestmove' && data.move) {
      const move = this.parseMove(data.move);
      if (move) {
        this.siteAdapter.highlightMove(move.from, move.to);
        this.logger.info('Best move highlighted:', data.move);
      }

      this.ui.updateAnalysis({
        bestmove: data.move
      });
    } else if (data.type === 'analysis') {
      this.ui.updateAnalysis({
        evaluation: data.score,
        depth: data.depth,
        mate: data.mate
      });
    }
  }

  parseMove(moveString) {
    if (moveString.length < 4) return null;

    return {
      from: moveString.substring(0, 2),
      to: moveString.substring(2, 4),
      promotion: moveString.length > 4 ? moveString[4] : null
    };
  }

  onBoardChange() {
    if (this.isAnalyzing) {
      clearTimeout(this.boardChangeTimeout);
      this.boardChangeTimeout = setTimeout(() => {
        this.analyzeCurrentPosition();
      }, 1000);
    }
  }

  destroy() {
    this.stopAnalysis();

    if (this.engine) {
      this.engine.destroy();
    }

    if (this.siteAdapter) {
      this.siteAdapter.destroy();
    }

    if (this.ui) {
      this.ui.destroy();
    }
  }
}

// Initialize the application
(function() {
  'use strict';

  function initCheessy() {
    const app = new ChessyApp();
    app.initialize().catch(console.error);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCheessy);
  } else {
    setTimeout(initCheessy, 2000);
  }
})();
