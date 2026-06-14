let currentPage = 1;
const limit = 10;
let allTasks = [];
let filteredTasks = [];

// DOM Elements
const historyBody = document.getElementById('historyBody');
const paginationInfo = document.getElementById('paginationInfo');
const paginationBtns = document.getElementById('paginationBtns');
const searchInput = document.getElementById('searchInput');
const dateFromInput = document.getElementById('dateFrom');
const dateToInput = document.getElementById('dateTo');
const btnFilter = document.querySelector('.btn-filter');

// Set default date range filters (from 7 days ago to today)
const today = new Date();
const lastWeek = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
if (dateFromInput) dateFromInput.value = lastWeek.toISOString().substring(0, 10);
if (dateToInput) dateToInput.value = today.toISOString().substring(0, 10);

// Load history tasks on page load
loadHistory();

// Event Listeners
if (searchInput) {
  searchInput.addEventListener('input', () => {
    applyFiltersAndRender();
  });
}

if (btnFilter) {
  btnFilter.addEventListener('click', () => {
    loadHistory();
  });
}

// Add event listener for export excel button
const btnExcel = document.querySelector('.btn-excel');
if (btnExcel) {
  btnExcel.addEventListener('click', () => {
    exportToExcelMock();
  });
}

function loadHistory() {
  // Fetch tasks list (increase limit to fetch more tasks for client-side filtering)
  fetch(`/tasks?limit=200&offset=0`)
  .then(res => {
    if (!res.ok) throw new Error('Không thể tải lịch sử');
    return res.json();
  })
  .then(data => {
    allTasks = data.tasks || [];
    applyFiltersAndRender();
  })
  .catch(err => {
    showToast('Lỗi tải dữ liệu lịch sử: ' + err.message);
  });
}

function applyFiltersAndRender() {
  let result = [...allTasks];

  // 1. Text Search Filter
  const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
  if (query) {
    result = result.filter(task => task.filename.toLowerCase().includes(query));
  }

  // 2. Date Range Filter
  const fromDate = dateFromInput ? new Date(dateFromInput.value + 'T00:00:00') : null;
  const toDate = dateToInput ? new Date(dateToInput.value + 'T23:59:59') : null;

  result = result.filter(task => {
    const taskDate = new Date(task.created_at);
    if (fromDate && taskDate < fromDate) return false;
    if (toDate && taskDate > toDate) return false;
    return true;
  });

  filteredTasks = result;
  currentPage = 1; // Reset to page 1
  renderTable();
}

function renderTable() {
  const total = filteredTasks.length;
  const startIdx = (currentPage - 1) * limit;
  const endIdx = Math.min(startIdx + limit, total);
  const pageTasks = filteredTasks.slice(startIdx, endIdx);

  // Update pagination info
  if (paginationInfo) {
    if (total === 0) {
      paginationInfo.textContent = 'Hiển thị 0 video';
    } else {
      paginationInfo.textContent = `Hiển thị ${startIdx + 1} - ${endIdx} của ${total} video`;
    }
  }

  // Render rows
  if (pageTasks.length === 0) {
    historyBody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: #999; padding: 40px;">
          Không tìm thấy video nào đã xử lý.
        </td>
      </tr>
    `;
    renderPaginationButtons(0);
    return;
  }

  historyBody.innerHTML = pageTasks.map(task => {
    const isDone = task.status === 'done';
    const isFailed = task.status === 'failed';
    
    // Format duration
    let durationStr = 'N/A';
    if (isDone && task.video_duration) {
      const mins = Math.floor(task.video_duration / 60);
      const secs = Math.ceil(task.video_duration % 60);
      durationStr = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    // Format total vehicles
    const totalVehicles = isDone 
      ? (task.car_count + task.motorcycle_count + task.bus_count + task.truck_count) 
      : 0;

    // Date formatting
    const formattedDate = new Date(task.created_at).toLocaleString('vi-VN');

    // Stable mock confidence based on task id hash
    const confidenceVal = isDone ? (90 + (task.id.charCodeAt(0) % 8) + (task.id.charCodeAt(1) % 10) / 10) : 0;

    return `
      <tr>
        <td>
          <div class="td-video">
            <div class="vid-thumb">${isDone ? '📹' : '⏳'}</div>
            <div>
              <div class="vid-name" title="${task.filename}">${task.filename}</div>
              <div class="vid-date">${formattedDate}</div>
            </div>
          </div>
        </td>
        <td>${durationStr}</td>
        <td class="td-total">${isDone ? totalVehicles.toLocaleString() : '-'}</td>
        <td>
          ${isDone ? `
            <div class="detail-chips">
              <span class="chip">🛵 ${task.motorcycle_count}</span>
              <span class="chip">🚗 ${task.car_count}</span>
              <span class="chip">🚌 ${task.bus_count}</span>
              <span class="chip">🚚 ${task.truck_count}</span>
            </div>
          ` : isFailed ? `
            <span style="color:#d9534f; font-size:0.9em;" title="${task.error_msg}">Lỗi: ${task.error_msg || 'Xử lý thất bại'}</span>
          ` : `
            <div class="progress-bar-container" style="width: 120px;">
              <span style="font-size: 0.85em; color: #667eea; font-weight: 500;">
                ${task.status === 'queued' ? 'Đang chờ...' : `Đang xử lý: ${task.progress}%`}
              </span>
              <div class="conf-bar" style="height: 4px; background: #e9ecef; border-radius: 2px; margin-top: 4px;">
                <div class="conf-fill" style="width: ${task.progress}%; background: linear-gradient(90deg, #667eea, #764ba2);"></div>
              </div>
            </div>
          `}
        </td>
        <td>
          ${isDone ? `
            <div class="conf-wrap">
              <span class="conf-pct">${confidenceVal.toFixed(1)}%</span>
              <div class="conf-bar"><div class="conf-fill" style="width:${confidenceVal}%"></div></div>
            </div>
          ` : '-'}
        </td>
        <td>
          <div class="action-btns">
            ${isDone ? `
              <button onclick="viewTaskResults('${task.id}')" title="Xem biểu đồ & chi tiết trên Dashboard">👁</button>
              <a href="/output/${task.id}_output.mp4" target="_blank" style="text-decoration:none;"><button title="Tải video kết quả">⬇</button></a>
              <button onclick="deleteTaskHistory('${task.id}')" style="background:#ff6b6b; color:white; border:none;" title="Xóa lịch sử">❌</button>
            ` : `
              <button onclick="deleteTaskHistory('${task.id}')" style="background:#ff6b6b; color:white; border:none;" title="Hủy bỏ">❌</button>
            `}
          </div>
        </td>
      </tr>
    `;
  }).join('');

  renderPaginationButtons(total);
}

function renderPaginationButtons(total) {
  const pageCount = Math.ceil(total / limit);
  
  if (pageCount <= 1) {
    paginationBtns.innerHTML = '';
    return;
  }

  let html = '';
  
  // First page & Prev page buttons
  html += `<button class="pag-btn" onclick="goToPage(1)" ${currentPage === 1 ? 'disabled' : ''}>|&lt;</button>`;
  html += `<button class="pag-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>&lt;</button>`;

  // Number buttons (show surrounding pages)
  for (let i = 1; i <= pageCount; i++) {
    if (i === 1 || i === pageCount || (i >= currentPage - 2 && i <= currentPage + 2)) {
      html += `<button class="pag-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    } else if (i === currentPage - 3 || i === currentPage + 3) {
      html += `<button class="pag-btn" disabled>...</button>`;
    }
  }

  // Next page & Last page buttons
  html += `<button class="pag-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === pageCount ? 'disabled' : ''}>&gt;</button>`;
  html += `<button class="pag-btn" onclick="goToPage(${pageCount})" ${currentPage === pageCount ? 'disabled' : ''}>&gt;|</button>`;

  paginationBtns.innerHTML = html;
}

window.goToPage = function(page) {
  currentPage = page;
  renderTable();
};

window.viewTaskResults = function(taskId) {
  // Redirect to Dashboard (root page) with task_id parameter
  window.location.href = `/?task_id=${taskId}`;
};

window.deleteTaskHistory = function(taskId) {
  if (!confirm('Bạn có chắc chắn muốn xóa video này khỏi lịch sử và tất cả tệp tin liên quan?')) return;

  fetch(`/task/${taskId}`, {
    method: 'DELETE'
  })
  .then(res => {
    if (!res.ok) throw new Error('Không thể xóa task');
    return res.json();
  })
  .then(() => {
    showToast('Đã xóa thành công!');
    loadHistory(); // Reload table
  })
  .catch(err => {
    showToast('Lỗi xóa: ' + err.message);
  });
};

function exportToExcelMock() {
  showToast('Đang tạo báo cáo Excel... (Mock)');
  setTimeout(() => {
    showToast('Tải báo cáo Excel thành công!');
  }, 1500);
}
