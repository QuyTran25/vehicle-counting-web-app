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

// Hide progress section initially
const progressSection = document.getElementById('progressSection');
if (progressSection) {
  progressSection.style.display = 'none';
}

// Set up event listeners for dropZone
if (dropZone) {
  dropZone.addEventListener('click', () => fileInput.click());

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
  if (!file.type.startsWith('video/') && !file.name.endsWith('.mp4') && !file.name.endsWith('.avi') && !file.name.endsWith('.mov') && !file.name.endsWith('.mkv')) {
    showToast('Vui lòng chọn tệp tin video hợp lệ.');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  // Show progress section
  if (progressSection) progressSection.style.display = 'block';
  progressFill.style.width = '0%';
  progressLabel.textContent = 'Đang tải video lên...';
  progressTime.textContent = '';
  processingBadge.classList.add('hidden');

  fetch('/upload', {
    method: 'POST',
    body: formData
  })
  .then(async res => {
    if (!res.ok) {
      // Parse FastAPI error response
      let errorMsg = 'Tải lên thất bại';
      try {
        const errorData = await res.json();
        if (errorData && errorData.detail) {
          // FastAPI HTTPException format: {"detail": "error message"}
          errorMsg = errorData.detail;
        } else if (errorData && errorData.message) {
          errorMsg = errorData.message;
        } else {
          // Fallback for non-JSON errors
          errorMsg = `Lỗi ${res.status}: ${res.statusText}`;
        }
      } catch (e) {
        // If JSON parse fails, use status text
        errorMsg = `Lỗi ${res.status}: ${res.statusText}`;
      }
      
      // Special handling for specific error codes
      if (res.status === 400) {
        showToast('⚠️ ' + errorMsg);
        progressLabel.textContent = 'File không hợp lệ: ' + errorMsg;
      } else if (res.status === 413) {
        showToast('⚠️ File quá lớn. Vui lòng chọn video nhỏ hơn.');
        progressLabel.textContent = 'File quá lớn.';
      } else {
        showToast('❌ Lỗi: ' + errorMsg);
        progressLabel.textContent = 'Lỗi tải video: ' + errorMsg;
      }
      return;
    }
    return res.json();
  })
  .then(data => {
    if (!data) return;
    showToast('✓ Tải video thành công, đang xếp hàng xử lý.');
    pollStatus(data.task_id);
  })
  .catch(err => {
    showToast('❌ Lỗi kết nối: ' + err.message);
    progressLabel.textContent = 'Lỗi kết nối server.';
  });
}

function pollStatus(taskId) {
  // Setup realtime stream
  const liveStream = document.getElementById('liveStream');
  const outputVideo = document.getElementById('outputVideo');
  const dropContent = document.getElementById('dropContent');
  
  if (liveStream) {
    liveStream.src = `/stream/${taskId}`;
    liveStream.style.display = 'block';
  }
  if (outputVideo) {
    outputVideo.style.display = 'none';
  }
  if (dropContent) {
    dropContent.style.display = 'none';
  }

  const interval = setInterval(() => {
    fetch(`/status/${taskId}`)
    .then(res => {
      if (!res.ok) throw new Error('Lỗi kiểm tra trạng thái');
      return res.json();
    })
    .then(data => {
      const progress = data.progress || 0;
      
      // Realtime stats update
      if (data.live_stats) {
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
        clearInterval(interval);
        showToast('Xử lý video hoàn thành!');
        
        // Final fetch to ensure complete results and show final video
        fetchResults(taskId);
        
        // Hide stream
        if (liveStream) {
          liveStream.style.display = 'none';
          liveStream.src = '';
        }
      } else if (data.status === 'failed') {
        progressLabel.textContent = `Lỗi: ${data.error_msg || 'Xử lý thất bại'}`;
        processingBadge.classList.add('hidden');
        clearInterval(interval);
        showToast('Lỗi xử lý video!');
        
        // Hide stream and show drop zone
        if (liveStream) {
          liveStream.style.display = 'none';
          liveStream.src = '';
        }
        if (dropContent) {
          dropContent.style.display = 'flex';
        }
      }
    })
    .catch(err => {
      console.error(err);
    });
  }, 1000);
}

function updateUIRealtime(stats) {
  // Use the full updateUI function to redraw everything (charts, lists, totals)
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
  // 1. Calculate In/Out stats from events list
  let totalIn = 0;
  let totalOut = 0;
  
  const classStats = {
    car: { in: 0, out: 0, label: 'Ô tô', icon: '🚗' },
    motorcycle: { in: 0, out: 0, label: 'Xe máy', icon: '🛵' },
    bus: { in: 0, out: 0, label: 'Xe buýt', icon: '🚌' },
    truck: { in: 0, out: 0, label: 'Xe tải', icon: '🚚' }
  };

  if (result.events && Array.isArray(result.events)) {
    result.events.forEach(evt => {
      let cls = evt.class;
      if (cls === 'motorbike') cls = 'motorcycle'; // mapping normalization
      
      if (evt.direction === 'in') {
        totalIn++;
        if (classStats[cls]) classStats[cls].in++;
      } else if (evt.direction === 'out') {
        totalOut++;
        if (classStats[cls]) classStats[cls].out++;
      }
    });
  }

  // Fallback to summary counts if no events crossed
  const totalVehicles = result.summary ? result.summary.total : (totalIn + totalOut);

  // 2. Update overall cards
  statTotal.textContent = totalVehicles.toLocaleString();
  statIn.textContent = totalIn.toLocaleString();
  statOut.textContent = totalOut.toLocaleString();

  // 3. Update vehicle breakdown list
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

  // 4. Update the line chart
  const duration = Math.ceil(result.metadata.video_duration);
  const labels = Array.from({length: duration + 1}, (_, i) => `${i}s`);
  const inData = Array(duration + 1).fill(0);
  const outData = Array(duration + 1).fill(0);

  if (result.events && Array.isArray(result.events)) {
    result.events.forEach(evt => {
      const sec = Math.floor(evt.timestamp);
      if (sec <= duration) {
        if (evt.direction === 'in') {
          inData[sec]++;
        } else if (evt.direction === 'out') {
          outData[sec]++;
        }
      }
    });
  }

  // Cumulate or smooth values for line chart look
  let cumIn = 0;
  let cumOut = 0;
  const cumInData = inData.map(val => cumIn += val);
  const cumOutData = outData.map(val => cumOut += val);

  trafficChartInstance.data.labels = labels;
  trafficChartInstance.data.datasets[0].data = cumInData;
  trafficChartInstance.data.datasets[1].data = cumOutData;
  trafficChartInstance.update();

  // 5. Update processed time duration label
  if (progressTime) {
    const mins = Math.floor(duration / 60);
    const secs = duration % 60;
    const durationStr = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    progressTime.textContent = `${durationStr} / ${durationStr}`;
  }

  // 6. Show final output video player
  const outputVideo = document.getElementById('outputVideo');
  const dropContent = document.getElementById('dropContent');
  const liveStream = document.getElementById('liveStream');
  if (outputVideo && result.output_video) {
    outputVideo.src = result.output_video;
    outputVideo.style.display = 'block';
    if (dropContent) dropContent.style.display = 'none';
    if (liveStream) liveStream.style.display = 'none';
  }
}

// On Page Load: check if task_id parameter exists
window.addEventListener('DOMContentLoaded', () => {
  const urlParams = new URLSearchParams(window.location.search);
  const taskId = urlParams.get('task_id');
  
  if (taskId) {
    if (progressSection) progressSection.style.display = 'block';
    progressLabel.textContent = 'Đang tải kết quả...';
    progressFill.style.width = '20%';
    
    // Check status first to see if it's still processing
    fetch(`/status/${taskId}`)
      .then(res => res.json())
      .then(data => {
        if (data.status === 'done') {
          fetchResults(taskId);
        } else if (data.status === 'failed') {
          progressLabel.textContent = `Lỗi: ${data.error_msg}`;
        } else {
          // Task is processing or queued, start live polling
          pollStatus(taskId);
        }
      })
      .catch(() => fetchResults(taskId)); // fallback
  } else {
    // No task_id in URL, check if there is an active running task
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
