
const ctx = document.getElementById('trafficChart').getContext('2d');

const labels = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00', '24:00'];
const inData = [200, 400, 250, 700, 300, 1000, 250, 800, 500]; 
const outData = [150, 300, 200, 500, 200, 750, 150, 600, 400];

new Chart(ctx, {
  type: 'line',
  data: {
    labels: labels,
    datasets: [
      {
        data: inData,
        borderColor: '#0041C8',
        backgroundColor: 'rgba(0,65,200,0.10)',
        borderWidth: 3,
        fill: true,
        tension: 0.45,
        pointRadius: 0
      },
      {
        data: outData,
        borderColor: '#924C00',
        backgroundColor: 'rgba(146,76,0,0.08)',
        borderWidth: 3,
        fill: true,
        tension: 0.45,
        pointRadius: 0
      }
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { font: { family: 'Roboto' } } },
      y: { display: false, beginAtZero: true } 
    }
  }
});
