// Initialize trafficChart with initial empty state
const ctx = document.getElementById('trafficChart').getContext('2d');
let trafficChartInstance = new Chart(ctx, {
  type: 'line',
  data: {
    labels: ['0s'],
    datasets: [
      {
        label: 'Số xe vào',
        data: [0],
        borderColor: '#0041C8',
        backgroundColor: 'rgba(0,65,200,0.10)',
        borderWidth: 3,
        fill: true,
        tension: 0.45,
        pointRadius: 2
      },
      {
        label: 'Số xe ra',
        data: [0],
        borderColor: '#924C00',
        backgroundColor: 'rgba(146,76,0,0.08)',
        borderWidth: 3,
        fill: true,
        tension: 0.45,
        pointRadius: 2
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false }
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { font: { family: 'Roboto' } }
      },
      y: {
        beginAtZero: true,
        ticks: { font: { family: 'Roboto' } }
      }
    }
  }
});

// DOM Elements
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const processingBadge = document.getElementById('processingBadge');
const progressLabel = document.getElementById('progressLabel');
const progressTime = document.getElementById('progressTime');
const progressFill = document.getElementById('progressFill');
const statTotal = document.getElementById('statTotal');
const statIn = document.getElementById('statIn');
const statOut = document.getElementById('statOut');
const vehicleList = document.getElementById('vehicleList');
const progressSection = document.getElementById('progressSection');

// New DOM Elements for Manual Mode
const laneSelector = document.getElementById('laneSelector');
const anchorSelector = document.getElementById('anchorSelector');
const modeSelector = document.getElementById('modeSelector');
const modeAuto = document.getElementById('modeAuto');
const modeManual = document.getElementById('modeManual');
const canvasOverlay = document.getElementById('canvasOverlay');
const lineCanvas = document.getElementById('lineCanvas');
const lineTools = document.getElementById('lineTools');
const lineInfo = document.getElementById('lineInfo');
const processBtn = document.getElementById('processBtn');
const warningMsg = document.getElementById('warningMsg');
const warningText = document.getElementById('warningText');

// State Variables
let currentTaskId = null;
let currentMode = 'auto'; // 'auto' | 'manual'
let autoLaneMode = 'dual'; // 'single' | 'dual'
let manualAnchorMode = 'BOTTOM_CENTER'; // 'BOTTOM_CENTER' | 'CENTER'
let activeTool = 'draw'; // 'draw' | 'select'
let originalVideoWidth = 1920;
let originalVideoHeight = 1080;
let manualLines = []; // [{id, label, x1, y1, x2, y2, flip_direction, count_mode}]
let activeLineIndex = -1;
let isDrawing = false;
let drawStartPoint = null;
let firstFrameImg = null;

// Constants - must match server-side values
const MAX_LINES = 2;
const MIN_LINES = 1;

// Hide elements initially
if (progressSection) progressSection.style.display = 'none';
if (lineTools) lineTools.style.display = 'none';
if (processBtn) processBtn.style.display = 'none';

// Mode button listeners
if (modeAuto && modeManual) {
  modeAuto.addEventListener('click', (e) => {
    e.stopPropagation();
    setProcessingMode('auto');
  });
  modeManual.addEventListener('click', (e) => {
    e.stopPropagation();
    setProcessingMode('manual');
  });
}

function setProcessingMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(btn => btn.classList.remove('active'));
  if (mode === 'auto') {
    modeAuto.classList.add('active');
    if (laneSelector) laneSelector.style.display = 'flex';
    if (anchorSelector) anchorSelector.style.display = 'none';
    resetCanvasOverlay();
    if (lineTools) lineTools.style.display = 'none';
  } else {
    modeManual.classList.add('active');
    if (laneSelector) laneSelector.style.display = 'none';
    if (anchorSelector) anchorSelector.style.display = 'flex';
    resetCanvasOverlay();
    if (lineTools) lineTools.style.display = 'flex';

    // Reset and show the drop content for manual mode
    const dropContent = document.getElementById('dropContent');
    if (dropContent) {
      dropContent.innerHTML = `
        <div class="drop-icon"></div>
        <div class="drop-label">Kéo thả file vào đây</div>
        <div class="drop-hint">hoặc click để chọn tệp tin (MP4, AVI, MOV)</div>
      `;
      dropContent.style.display = 'flex';
    }
    showToast('Đã chuyển sang chế độ vẽ thủ công. Vui lòng upload video để bắt đầu vẽ line.');
  }
}

function resetCanvasOverlay() {
  const liveStream = document.getElementById('liveStream');
  const outputVideo = document.getElementById('outputVideo');
  const dropContent = document.getElementById('dropContent');

  if (liveStream) liveStream.style.display = 'none';
  if (outputVideo) outputVideo.style.display = 'none';
  if (lineCanvas) lineCanvas.style.display = 'none';
  if (dropContent) dropContent.style.display = 'flex';

  if (processBtn) processBtn.style.display = 'none';
  if (warningMsg) warningMsg.classList.remove('active');

  manualLines = [];
  activeLineIndex = -1;
  firstFrameImg = null;
  updateLineInfoTags();
}

// Set up event listeners for dropZone
if (dropZone) {
  dropZone.addEventListener('click', () => {
    // Only trigger file select if no video is currently loaded on canvas
    if (currentMode === 'manual' && firstFrameImg) return;
    fileInput.click();
  });

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
      handleVideoUpload(e.dataTransfer.files[0]);
    }
  });
}

if (fileInput) {
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleVideoUpload(e.target.files[0]);
    }
  });
}

function handleVideoUpload(file) {
  if (!file) return;

  // Validate file type
  const allowedExtensions = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'];
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  if (!allowedExtensions.includes(ext)) {
    showToast('Vui lòng chọn tệp tin video hợp lệ.');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  formData.append('single_lane', autoLaneMode === 'single' ? 'true' : 'false');
  formData.append('mode', currentMode);

  // Show progress section
  if (progressSection) progressSection.style.display = 'block';
  progressFill.style.width = '0%';
  progressLabel.textContent = 'Đang tải video lên...';
  progressTime.textContent = '';
  processingBadge.classList.add('hidden');
  resetCanvasOverlay();

  fetch('/upload', {
    method: 'POST',
    body: formData
  })
    .then(async res => {
      if (!res.ok) {
        let errorMsg = 'Tải lên thất bại';
        try {
          const errorData = await res.json();
          errorMsg = errorData.detail || errorData.message || errorMsg;
        } catch (e) { }
        showToast('⚠️ ' + errorMsg);
        progressLabel.textContent = 'Lỗi: ' + errorMsg;
        return;
      }
      return res.json();
    })
    .then(data => {
      if (!data) return;
      currentTaskId = data.task_id;

      if (currentMode === 'manual') {
        showToast('✓ Đã tải video thành công. Vui lòng vẽ vạch đếm.');
        progressLabel.textContent = 'Đang lấy frame đầu để vẽ line...';
        loadFirstFrame(data.task_id);
      } else {
        showToast('✓ Tải video thành công, đang phân tích tự động.');
        pollStatus(data.task_id);
      }
    })
    .catch(err => {
      showToast('❌ Lỗi kết nối: ' + err.message);
      progressLabel.textContent = 'Lỗi kết nối server.';
    });
}

// ═══════════════════════════════════════════════════════════════════
// Manual Line Drawing Logic
// ═══════════════════════════════════════════════════════════════════

function loadFirstFrame(taskId) {
  const url = `/tasks/${taskId}/first-frame`;
  progressLabel.textContent = 'Đang lấy hình ảnh xem trước...';

  fetch(url)
    .then(async res => {
      if (!res.ok) throw new Error('Không thể tải frame video.');
      originalVideoWidth = parseInt(res.headers.get('X-Video-Width') || '1920');
      originalVideoHeight = parseInt(res.headers.get('X-Video-Height') || '1080');

      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);

      firstFrameImg = new Image();
      firstFrameImg.onload = function () {
        setupCanvas();
        URL.revokeObjectURL(objectUrl);
      };
      firstFrameImg.onerror = function () {
        showToast('❌ Không thể tải frame video.');
        progressLabel.textContent = 'Lỗi lấy hình ảnh xem trước.';
        URL.revokeObjectURL(objectUrl);
      };
      firstFrameImg.src = objectUrl;
    })
    .catch(err => {
      showToast('❌ ' + err.message);
      progressLabel.textContent = 'Lỗi kết nối server.';
    });
}

function setupCanvas() {
  const dropContent = document.getElementById('dropContent');
  if (dropContent) dropContent.style.display = 'none';

  // Show canvas inside drop-zone
  if (lineCanvas) {
    lineCanvas.style.display = 'block';
  }
  if (lineTools) lineTools.style.display = 'flex';
  if (processBtn) {
    processBtn.style.display = 'block';
    processBtn.disabled = true;
  }
  progressLabel.textContent = 'Mời bạn vẽ từ 1 đến 2 vạch đếm trên khung hình.';

  // Resize canvas based on aspect ratio of the image and drop-zone dimensions
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);

  // Attach Canvas Mouse Listeners
  lineCanvas.addEventListener('mousedown', handleMouseDown);
  lineCanvas.addEventListener('mousemove', handleMouseMove);
  lineCanvas.addEventListener('mouseup', handleMouseUp);
}

function resizeCanvas() {
  if (!firstFrameImg || !lineCanvas) return;
  const dropZoneEl = document.getElementById('dropZone');
  const parent = dropZoneEl ? dropZoneEl.getBoundingClientRect() : { width: 800, height: 450 };
  const parentWidth = parent.width || 800;

  const videoAspect = originalVideoWidth / originalVideoHeight;
  // Set internal canvas resolution to original video size for precise coordinate mapping
  lineCanvas.width = originalVideoWidth;
  lineCanvas.height = originalVideoHeight;
  // CSS size to naturally fit the drop-zone via HTML style
  lineCanvas.style.width = '100%';
  lineCanvas.style.height = 'auto';

  drawCanvas();
}

function drawCanvas() {
  if (!lineCanvas) return;
  const ctx = lineCanvas.getContext('2d');
  const w = lineCanvas.width;
  const h = lineCanvas.height;
  ctx.clearRect(0, 0, w, h);

  if (firstFrameImg) {
    ctx.drawImage(firstFrameImg, 0, 0, w, h);
  }

  // Draw manual lines - coordinates already match canvas internal resolution
  manualLines.forEach((line, index) => {
    const isSelected = (index === activeLineIndex);
    const color = isSelected ? '#ffc107' : (index === 0 ? '#00ffff' : '#ff8000');

    // Points are already in canvas coordinates (which matches original video resolution)
    const x1 = line.x1;
    const y1 = line.y1;
    const x2 = line.x2;
    const y2 = line.y2;

    // Draw main line
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.lineWidth = isSelected ? 4 : 3;
    ctx.strokeStyle = color;
    ctx.stroke();

    // Draw nodes
    ctx.beginPath();
    ctx.arc(x1, y1, 6, 0, 2 * Math.PI);
    ctx.arc(x2, y2, 6, 0, 2 * Math.PI);
    ctx.fillStyle = '#000';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(x1, y1, 4, 0, 2 * Math.PI);
    ctx.arc(x2, y2, 4, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // Draw direction arrow
    drawDirectionArrow(ctx, x1, y1, x2, y2, line.flip_direction, color);
  });

  // Draw current line preview during mouse drag
  if (isDrawing && drawStartPoint && lineCanvas) {
    const rect = lineCanvas.getBoundingClientRect();
    // Scale preview to CSS display coordinates
    const px1 = (drawStartPoint.x / lineCanvas.width) * rect.width;
    const py1 = (drawStartPoint.y / lineCanvas.height) * rect.height;
    const px2 = (drawStartPoint.currentX / lineCanvas.width) * rect.width;
    const py2 = (drawStartPoint.currentY / lineCanvas.height) * rect.height;

    const ctx = lineCanvas.getContext('2d');
    ctx.save();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 3;
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(px1, py1);
    ctx.lineTo(px2, py2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }
}

function drawDirectionArrow(ctx, x1, y1, x2, y2, isFlipped, color) {
  // Midpoint
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;

  // Angle of the line
  const angle = Math.atan2(y2 - y1, x2 - x1);

  // Normal/perpendicular vector pointing one side (in vs out)
  const normAngle = angle + (isFlipped ? -Math.PI / 2 : Math.PI / 2);
  const arrowLength = 20;

  const ax1 = mx;
  const ay1 = my;
  const ax2 = mx + Math.cos(normAngle) * arrowLength;
  const ay2 = my + Math.sin(normAngle) * arrowLength;

  // Draw perpendicular stem
  ctx.beginPath();
  ctx.moveTo(ax1, ay1);
  ctx.lineTo(ax2, ay2);
  ctx.lineWidth = 2;
  ctx.strokeStyle = color;
  ctx.stroke();

  // Draw Arrow Head at end
  const headlen = 8; // length of head in pixels
  ctx.beginPath();
  ctx.moveTo(ax2, ay2);
  ctx.lineTo(ax2 - headlen * Math.cos(normAngle - Math.PI / 6), ay2 - headlen * Math.sin(normAngle - Math.PI / 6));
  ctx.lineTo(ax2 - headlen * Math.cos(normAngle + Math.PI / 6), ay2 - headlen * Math.sin(normAngle + Math.PI / 6));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();

  // Text label: IN (side arrow points to) or OUT (opposite)
  ctx.font = 'bold 10px Roboto';
  ctx.fillStyle = '#ffffff';
  ctx.fillText(isFlipped ? 'OUT' : 'IN', ax2 + 5, ay2 + 5);
}

// Canvas interaction handlers
function handleMouseDown(e) {
  if (!lineCanvas) return;
  const rect = lineCanvas.getBoundingClientRect();
  // Get position relative to CSS-displayed canvas size
  const cssX = e.clientX - rect.left;
  const cssY = e.clientY - rect.top;
  // Scale to internal canvas resolution
  const x = (cssX / rect.width) * lineCanvas.width;
  const y = (cssY / rect.height) * lineCanvas.height;

  if (activeTool === 'draw') {
    if (manualLines.length >= MAX_LINES) {
      showToast('⚠️ Bạn chỉ có thể vẽ tối đa 2 vạch đếm.');
      return;
    }
    isDrawing = true;
    drawStartPoint = { x, y, currentX: x, currentY: y, cssX, cssY, currentCssX: cssX, currentCssY: cssY };
  } else if (activeTool === 'select') {
    let foundIndex = -1;
    let minDist = 15 * Math.max(lineCanvas.width / rect.width, lineCanvas.height / rect.height);

    manualLines.forEach((line, index) => {
      const dist = distToSegment({ x, y }, { x: line.x1, y: line.y1 }, { x: line.x2, y: line.y2 });
      if (dist < minDist) {
        foundIndex = index;
        minDist = dist;
      }
    });

    activeLineIndex = foundIndex;
    drawCanvas();
    updateLineInfoTags();
  }
}

function handleMouseMove(e) {
  if (!isDrawing || !drawStartPoint || !lineCanvas) return;
  const rect = lineCanvas.getBoundingClientRect();
  const cssX = e.clientX - rect.left;
  const cssY = e.clientY - rect.top;
  drawStartPoint.currentX = (cssX / rect.width) * lineCanvas.width;
  drawStartPoint.currentY = (cssY / rect.height) * lineCanvas.height;
  drawStartPoint.currentCssX = cssX;
  drawStartPoint.currentCssY = cssY;
  drawCanvas();
}

function handleMouseUp(e) {
  if (!isDrawing || !drawStartPoint || !lineCanvas) return;
  isDrawing = false;

  const rect = lineCanvas.getBoundingClientRect();
  const endCssX = e.clientX - rect.left;
  const endCssY = e.clientY - rect.top;
  const endX = (endCssX / rect.width) * lineCanvas.width;
  const endY = (endCssY / rect.height) * lineCanvas.height;

  // Calculate length to prevent dot clicks
  const len = Math.sqrt(Math.pow(endX - drawStartPoint.x, 2) + Math.pow(endY - drawStartPoint.y, 2));
  if (len < 30) {
    drawStartPoint = null;
    drawCanvas();
    return;
  }

  // Coordinates are already in original video resolution
  const origX1 = Math.round(drawStartPoint.x);
  const origY1 = Math.round(drawStartPoint.y);
  const origX2 = Math.round(endX);
  const origY2 = Math.round(endY);

  const lineId = `L${manualLines.length + 1}`;
  const label = `Vạch ${manualLines.length + 1}`;

  manualLines.push({
    id: lineId,
    label: label,
    x1: origX1,
    y1: origY1,
    x2: origX2,
    y2: origY2,
    flip_direction: false,
    count_mode: 'both'
  });

  activeLineIndex = manualLines.length - 1;
  drawStartPoint = null;
  drawCanvas();
  updateLineInfoTags();
  validateProcessBtn();
}

// Distance point to line segment helper
function distToSegment(p, v, w) {
  const l2 = Math.pow(v.x - w.x, 2) + Math.pow(v.y - w.y, 2);
  if (l2 === 0) return Math.sqrt(Math.pow(p.x - v.x, 2) + Math.pow(p.y - v.y, 2));
  let t = ((p.x - v.x) * (w.x - v.x) + (p.y - v.y) * (w.y - v.y)) / l2;
  t = Math.max(0, Math.min(1, t));
  return Math.sqrt(Math.pow(p.x - (v.x + t * (w.x - v.x)), 2) + Math.pow(p.y - (v.y + t * (w.y - v.y)), 2));
}

// Line Drawing UI Control listeners
document.getElementById('toolDraw').addEventListener('click', () => setTool('draw'));
document.getElementById('toolSelect').addEventListener('click', () => setTool('select'));
document.getElementById('toolDelete').addEventListener('click', deleteActiveLine);
document.getElementById('toolFlip').addEventListener('click', flipActiveLineDirection);

function setTool(tool) {
  activeTool = tool;
  document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
  if (tool === 'draw') {
    document.getElementById('toolDraw').classList.add('active');
  } else {
    document.getElementById('toolSelect').classList.add('active');
  }
}

function deleteActiveLine() {
  if (activeLineIndex < 0 || activeLineIndex >= manualLines.length) return;
  manualLines.splice(activeLineIndex, 1);
  activeLineIndex = -1;
  // Re-index line IDs and labels
  manualLines.forEach((line, index) => {
    line.id = `L${index + 1}`;
    line.label = `Vạch ${index + 1}`;
  });
  drawCanvas();
  updateLineInfoTags();
  validateProcessBtn();
}

function flipActiveLineDirection() {
  if (activeLineIndex < 0 || activeLineIndex >= manualLines.length) return;
  manualLines[activeLineIndex].flip_direction = !manualLines[activeLineIndex].flip_direction;
  drawCanvas();
  updateLineInfoTags();
}

function updateLineInfoTags() {
  if (!lineInfo) return;
  lineInfo.innerHTML = manualLines.map((line, index) => {
    const isSelected = (index === activeLineIndex);
    const color = index === 0 ? '#00ffff' : '#ff8000';
    return `
      <div class="line-tag" style="border: 2px solid ${isSelected ? '#ffc107' : 'transparent'}">
        <div class="line-color" style="background: ${color}"></div>
        <span class="line-name">${line.label} (${line.flip_direction ? 'Đảo' : 'Chuẩn'})</span>
        <span class="line-remove" onclick="removeLineAtIndex(${index}, event)">×</span>
      </div>
    `;
  }).join('');
}

window.removeLineAtIndex = function (index, e) {
  e.stopPropagation();
  manualLines.splice(index, 1);
  activeLineIndex = -1;
  manualLines.forEach((line, idx) => {
    line.id = `L${idx + 1}`;
    line.label = `Vạch ${idx + 1}`;
  });
  drawCanvas();
  updateLineInfoTags();
  validateProcessBtn();
};

function validateProcessBtn() {
  if (!processBtn) return;
  if (manualLines.length >= MIN_LINES && manualLines.length <= MAX_LINES) {
    processBtn.disabled = false;
    if (warningMsg) warningMsg.classList.remove('active');
  } else {
    processBtn.disabled = true;
  }
}

// ⚠️ Process Triggering (Manual mode only)
if (processBtn) {
  processBtn.addEventListener('click', () => {
    if (manualLines.length === 0) {
      if (warningMsg && warningText) {
        warningText.textContent = 'Mời bạn vẽ line trước khi xử lý. Hãy vẽ ít nhất 1 line.';
        warningMsg.classList.add('active');
      }
      showToast('⚠️ Mời bạn vẽ ít nhất 1 line.');
      return;
    }

    processBtn.disabled = true;
    processBtn.querySelector('#processBtnText').textContent = 'Đang kích hoạt...';

    // 1. Save Lines Config to server
    fetch(`/tasks/${currentTaskId}/manual-lines`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lines: manualLines, trigger_anchor: manualAnchorMode })
    })
      .then(res => {
        if (!res.ok) throw new Error('Không thể lưu line config.');
        return res.json();
      })
      .then(() => {
        // 2. Trigger Video Processing
        return fetch(`/tasks/${currentTaskId}/process`, { method: 'POST' });
      })
      .then(res => {
        if (!res.ok) throw new Error('Kích hoạt phân tích thất bại.');
        return res.json();
      })
      .then(() => {
        showToast('✓ Bắt đầu xử lý với vạch kẻ tùy chỉnh của bạn.');
        if (canvasOverlay) canvasOverlay.classList.remove('active');
        if (lineTools) lineTools.style.display = 'none';
        if (processBtn) {
          processBtn.style.display = 'none';
          processBtn.querySelector('#processBtnText').textContent = 'Bắt đầu xử lý';
        }
        pollStatus(currentTaskId);
      })
      .catch(err => {
        showToast('❌ Lỗi: ' + err.message);
        processBtn.disabled = false;
        processBtn.querySelector('#processBtnText').textContent = 'Bắt đầu xử lý';
      });
  });
}

// ═══════════════════════════════════════════════════════════════════
// Status Polling & Results rendering
// ═══════════════════════════════════════════════════════════════════

function pollStatus(taskId) {
  currentTaskId = taskId;
  const liveStream = document.getElementById('liveStream');
  const outputVideo = document.getElementById('outputVideo');
  const dropContent = document.getElementById('dropContent');

  // Xóa interval cũ nếu có để tránh polling song song
  if (window.statusInterval) clearInterval(window.statusInterval);

  if (liveStream) {
    liveStream.src = `/stream/${taskId}`;
    liveStream.style.display = 'block';
  }
  if (outputVideo) outputVideo.style.display = 'none';
  if (dropContent) dropContent.style.display = 'none';

  window.statusInterval = setInterval(() => {
    fetch(`/status/${taskId}`)
      .then(res => {
        if (!res.ok) throw new Error('Lỗi kiểm tra trạng thái');
        return res.json();
      })
      .then(data => {
        const progress = data.progress || 0;
        console.log('[PollStatus]', data.status, 'live_stats:', data.live_stats ? 'YES' : 'NO');

        if (data.live_stats) {
          console.log('[Realtime] Calling updateUIRealtime...');
          updateUIRealtime(data.live_stats);
        }

        if (data.status === 'queued') {
          progressLabel.textContent = 'Đang chờ xử lý...';
          progressFill.style.width = '0%';
          processingBadge.classList.add('hidden');
        } else if (data.status === 'processing') {
          progressLabel.textContent = `Tiến độ phân tích: ${progress}%`;
          progressFill.style.width = `${progress}%`;
          processingBadge.classList.remove('hidden');
        } else if (data.status === 'done') {
          progressLabel.textContent = 'Hoàn thành phân tích!';
          progressFill.style.width = '100%';
          processingBadge.classList.add('hidden');
          clearInterval(window.statusInterval);
          showToast('Xử lý video hoàn thành!');

          fetchResults(taskId);

          if (liveStream) {
            liveStream.style.display = 'none';
            liveStream.src = '';
          }
        } else if (data.status === 'failed') {
          progressLabel.textContent = `Lỗi: ${data.error_msg || 'Xử lý thất bại'}`;
          processingBadge.classList.add('hidden');
          clearInterval(window.statusInterval);
          showToast('Lỗi xử lý video!');

          if (liveStream) {
            liveStream.style.display = 'none';
            liveStream.src = '';
          }
          if (dropContent) dropContent.style.display = 'flex';
        }
      })
      .catch(err => {
        console.error(err);
      });
  }, 2000); // Polling mỗi 2 giây thay vì 1 giây
}

function updateUIRealtime(stats) {
  console.log('[Realtime] Stats received:', stats);
  if (!stats || !stats.events) {
    console.warn('[Realtime] No events in stats, skipping');
    return;
  }
  updateUI(stats);
}

function fetchResults(taskId) {
  fetch(`/result/${taskId}`)
    .then(res => {
      if (!res.ok) throw new Error('Không thể tải kết quả');
      return res.json();
    })
    .then(result => {
      updateUI(result);
    })
    .catch(err => {
      showToast('Lỗi tải kết quả: ' + err.message);
    });
}

function updateUI(result) {
  try {
    let totalIn = 0;
    let totalOut = 0;

    const classStats = {
      car: { in: 0, out: 0, label: 'Ô tô', icon: '' },
      motorcycle: { in: 0, out: 0, label: 'Xe máy', icon: '' },
      bus: { in: 0, out: 0, label: 'Xe buýt', icon: '' },
      truck: { in: 0, out: 0, label: 'Xe tải', icon: '' }
    };

    if (result.events && Array.isArray(result.events)) {
      result.events.forEach(evt => {
        let cls = evt.class;
        if (cls === 'motorbike') cls = 'motorcycle';

        if (evt.direction === 'in') {
          totalIn++;
          if (classStats[cls]) classStats[cls].in++;
        } else if (evt.direction === 'out') {
          totalOut++;
          if (classStats[cls]) classStats[cls].out++;
        }
      });
    }

    const totalVehicles = (result.summary && result.summary.total != null) ? result.summary.total : (totalIn + totalOut);

    statTotal.textContent = totalVehicles.toLocaleString();
    statIn.textContent = totalIn.toLocaleString();
    statOut.textContent = totalOut.toLocaleString();

    vehicleList.innerHTML = Object.keys(classStats).map(key => {
      const stat = classStats[key];
      return `
        <div class="vehicle-row">
          <div class="vehicle-name"><span class="vehicle-icon">${stat.icon}</span>${stat.label}</div>
          <div class="vehicle-counts">
            <div class="vehicle-dir"><span class="dir-lbl">VÀO</span><span class="dir-val-in">${stat.in}</span></div>
            <div class="vdivider"></div>
            <div class="vehicle-dir"><span class="dir-lbl">RA</span><span class="dir-val-out">${stat.out}</span></div>
          </div>
        </div>
      `;
    }).join('');

    const duration = (result.metadata && result.metadata.video_duration != null)
      ? Math.ceil(result.metadata.video_duration)
      : Math.max(totalIn + totalOut, 10);
    const safeDuration = Math.max(duration, 0);
    const labels = Array.from({ length: safeDuration + 1 }, (_, i) => `${i}s`);
    const inData = Array(safeDuration + 1).fill(0);
    const outData = Array(safeDuration + 1).fill(0);

    if (result.events && Array.isArray(result.events)) {
      result.events.forEach(evt => {
        const sec = Math.floor(evt.timestamp);
        if (sec <= safeDuration) {
          if (evt.direction === 'in') {
            inData[sec]++;
          } else if (evt.direction === 'out') {
            outData[sec]++;
          }
        }
      });
    }

    let cumIn = 0;
    let cumOut = 0;
    const cumInData = inData.map(val => cumIn += val);
    const cumOutData = outData.map(val => cumOut += val);

    trafficChartInstance.data.labels = labels;
    trafficChartInstance.data.datasets[0].data = cumInData;
    trafficChartInstance.data.datasets[1].data = cumOutData;
    trafficChartInstance.update();

    if (progressTime) {
      const mins = Math.floor(safeDuration / 60);
      const secs = safeDuration % 60;
      const durationStr = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
      progressTime.textContent = `${durationStr} / ${durationStr}`;
    }

    const outputVideo = document.getElementById('outputVideo');
    const dropContent = document.getElementById('dropContent');
    const liveStream = document.getElementById('liveStream');
    if (outputVideo && result.output_video) {
      outputVideo.src = result.output_video;
      outputVideo.style.display = 'block';
      if (dropContent) dropContent.style.display = 'none';
      if (liveStream) liveStream.style.display = 'none';
    }
  } catch (err) {
    console.error('[updateUI] Error:', err);
  }
}

// On Page Load
window.addEventListener('DOMContentLoaded', () => {
  // Lane selector button handler (for auto mode)
  const laneBtns = document.querySelectorAll('#laneSelector .lane-btn');
  laneBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      laneBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      autoLaneMode = btn.dataset.mode;
    });
  });

  // Anchor selector button handler (for manual mode)
  const anchorBtns = document.querySelectorAll('#anchorSelector .lane-btn');
  anchorBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      anchorBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      manualAnchorMode = btn.dataset.anchor;
    });
  });

  const urlParams = new URLSearchParams(window.location.search);
  const taskId = urlParams.get('task_id');

  if (taskId) {
    if (progressSection) progressSection.style.display = 'block';
    progressLabel.textContent = 'Đang tải kết quả...';
    progressFill.style.width = '20%';

    fetch(`/status/${taskId}`)
      .then(res => res.json())
      .then(data => {
        if (data.status === 'done') {
          fetchResults(taskId);
        } else if (data.status === 'failed') {
          progressLabel.textContent = `Lỗi: ${data.error_msg}`;
        } else {
          pollStatus(taskId);
        }
      })
      .catch(() => fetchResults(taskId));
  } else {
    fetch('/tasks?limit=5')
      .then(res => res.json())
      .then(data => {
        if (data && data.tasks) {
          const activeTask = data.tasks.find(t => t.status === 'processing' || t.status === 'queued');
          if (activeTask) {
            if (progressSection) progressSection.style.display = 'block';
            pollStatus(activeTask.id);
          }
        }
      })
      .catch(err => console.error('Error checking active tasks:', err));
  }
});
