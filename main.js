import './style.css';

document.addEventListener('DOMContentLoaded', () => {
  // Views
  const viewLanding = document.getElementById('view-landing');
  const viewLogin = document.getElementById('view-login');
  const viewKyc = document.getElementById('view-kyc');
  const viewRetina = document.getElementById('view-retina');
  const viewDashboard = document.getElementById('view-dashboard');
  const viewFlow = document.getElementById('view-flow');
  
  // Forms & Buttons
  const loginForm = document.getElementById('login-form');
  const kycForm = document.getElementById('kyc-form');
  const routingForm = document.getElementById('routing-form');
  const quoteBtn = document.getElementById('quote-btn');
  const loader = quoteBtn.querySelector('.loader');
  const btnText = quoteBtn.querySelector('.btn-text');
  
  const quoteResults = document.getElementById('quote-results');
  const sendMoneyBtn = document.getElementById('send-money-btn');
  const executionTimeline = document.getElementById('execution-timeline');
  const flowSuccess = document.getElementById('flow-success');
  const finishBtn = document.getElementById('finish-btn');
  
  // Tabs
  const tabTransfer = document.getElementById('tab-transfer');
  const tabHistory = document.getElementById('tab-history');
  const tabMarket = document.getElementById('tab-market');
  
  const panelTransfer = document.getElementById('panel-transfer');
  const panelHistory = document.getElementById('panel-history');
  const panelMarket = document.getElementById('panel-market');
  const historyList = document.getElementById('history-list');
  
  let currentOptimalRoute = null;

  // --- RESET DEMO ---
  document.getElementById('reset-demo-btn').addEventListener('click', () => {
    if(confirm("Wipe all transaction history and reset the daily limit?")) {
      localStorage.clear();
      window.location.reload();
    }
  });

  function switchView(hideView, showView) {
    if(hideView) {
      hideView.style.display = 'none';
      hideView.classList.remove('active');
    }
    showView.style.display = 'block';
    showView.classList.add('active');
  }

  // --- STEP 0: LANDING ---
  document.getElementById('get-started-btn').addEventListener('click', () => {
    switchView(viewLanding, viewLogin);
  });

  // --- STEP 1: LOGIN ---
  loginForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const btn = loginForm.querySelector('button');
    btn.innerHTML = '<span class="loader" style="border-top-color:#fff;"></span> Authenticating...';
    
    setTimeout(() => {
      switchView(viewLogin, viewKyc);
    }, 800);
  });

  // --- STEP 2: KYC -> RETINA ---
  kycForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const btn = kycForm.querySelector('button');
    btn.innerHTML = '<span class="loader" style="border-top-color:#fff;"></span> Verifying TRISA...';
    
    setTimeout(() => {
      // Transition to Retina View
      switchView(viewKyc, viewRetina);
      runRetinaScan();
    }, 1000);
  });

  async function runRetinaScan() {
    const eye = document.querySelector('.scanner-eye');
    const border = document.getElementById('camera-border');
    const text = document.getElementById('scanner-text');
    const video = document.getElementById('webcam-feed');
    let stream = null;

    try {
      // Prompt user for real camera feed
      stream = await navigator.mediaDevices.getUserMedia({ video: true });
      video.srcObject = stream;
      text.textContent = 'SCANNING BIOMETRICS...';
      eye.classList.add('scanning');
    } catch (err) {
      console.warn("Camera access denied or unavailable. Simulating...", err);
      text.textContent = 'CAMERA UNAVAILABLE - SIMULATING SCAN...';
      eye.classList.add('scanning');
    }

    // Success animation after fake processing delay
    setTimeout(() => {
      eye.classList.remove('scanning');
      border.classList.add('success');
      text.textContent = 'MATCH FOUND. IDENTITY VERIFIED.';
      text.style.color = 'var(--success)';
      
      // Turn off camera light
      if (stream) {
        const tracks = stream.getTracks();
        tracks.forEach(track => track.stop());
      }
    }, 3500);

    // Proceed to Dashboard
    setTimeout(() => {
      switchView(viewRetina, viewDashboard);
      document.getElementById('header-sub').textContent = `KYC Verified: ${document.getElementById('kyc-name').value} | Limit: $50,000/day`;
    }, 4500);
  }

  // --- STEP 3: DASHBOARD TABS ---
  tabTransfer.addEventListener('click', () => {
    tabTransfer.classList.add('active');
    tabHistory.classList.remove('active');
    tabMarket.classList.remove('active');
    panelTransfer.style.display = 'block';
    panelHistory.style.display = 'none';
    panelMarket.style.display = 'none';
  });

  tabHistory.addEventListener('click', () => {
    tabHistory.classList.add('active');
    tabTransfer.classList.remove('active');
    tabMarket.classList.remove('active');
    panelHistory.style.display = 'block';
    panelTransfer.style.display = 'none';
    panelMarket.style.display = 'none';
    renderHistory();
  });

  tabMarket.addEventListener('click', () => {
    tabMarket.classList.add('active');
    tabTransfer.classList.remove('active');
    tabHistory.classList.remove('active');
    panelMarket.style.display = 'block';
    panelTransfer.style.display = 'none';
    panelHistory.style.display = 'none';
    renderChart();
  });

  // --- GET QUOTE ---
  routingForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    quoteBtn.disabled = true;
    btnText.style.display = 'none';
    loader.style.display = 'inline-block';
    
    const amount = parseFloat(document.getElementById('amount').value);

    // DAILY LIMIT CHECK ($50,000)
    const history = JSON.parse(localStorage.getItem('sb_history') || '[]');
    const today = new Date().toLocaleDateString();
    let dailyTotal = 0;
    history.forEach(tx => {
      if (new Date(tx.date).toLocaleDateString() === today) {
        dailyTotal += tx.source_amount;
      }
    });

    if (dailyTotal + amount > 50000) {
      alert(`TRANSACTION FAILED!\n\nYou are trying to send $${amount}, but you have already sent $${dailyTotal} today.\nThis exceeds your maximum daily regulatory limit of $50,000.`);
      quoteBtn.disabled = false;
      btnText.style.display = 'inline';
      loader.style.display = 'none';
      return;
    }

    const srcInput = document.getElementById('source_currency').value;
    const destInput = document.getElementById('dest_currency').value;
    const speed = document.querySelector('input[name="speed"]:checked').value;

    const payload = {
      source_currency: srcInput,
      destination_currency: destInput,
      amount: amount,
      sender_country: document.getElementById('kyc-nationality').value || "US",
      recipient_country: destInput.slice(0, 2),
      preferred_speed: speed
    };

    try {
      const response = await fetch('http://localhost:8000/api/v1/routes/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail?.message || "Route Unavailable");

      currentOptimalRoute = data;
      renderQuote(data);

    } catch (error) {
      alert("Error: " + error.message);
    } finally {
      quoteBtn.disabled = false;
      btnText.style.display = 'inline';
      loader.style.display = 'none';
    }
  });

  function renderQuote(data) {
    const formatFiatType = (cur) => new Intl.NumberFormat('en-US', { style: 'currency', currency: cur }).format;
    
    document.getElementById('quote-send').textContent = formatFiatType(data.source_currency)(data.source_amount);
    document.getElementById('quote-recv').textContent = formatFiatType(data.destination_currency)(data.destination_amount);
    document.getElementById('quote-fee').textContent = '$' + data.total_fee_usd.toFixed(2) + ` (${data.total_fee_percent.toFixed(2)}%)`;
    document.getElementById('quote-time').textContent = data.estimated_seconds.toFixed(1) + 's';
    
    quoteResults.style.opacity = '1';
    quoteResults.style.pointerEvents = 'auto';
    quoteResults.querySelector('.status-badge').textContent = 'Quote Locked (60s)';
    quoteResults.querySelector('.status-badge').style.background = 'rgba(0, 230, 118, 0.15)';
    quoteResults.querySelector('.status-badge').style.color = 'var(--success)';
    
    sendMoneyBtn.style.display = 'flex';
  }

  // --- SEND MONEY (EXECUTION FLOW) ---
  sendMoneyBtn.addEventListener('click', () => {
    if (!currentOptimalRoute) return;
    
    executionTimeline.innerHTML = '';
    
    addTimelineNode('Compliance & KYC', 'AML/Sanctions Screen', '0s', 'var(--warning)', 'Pending...', 'kyc-step');
    
    currentOptimalRoute.hops.forEach((hop, idx) => {
      let iconColor = 'var(--text-secondary)';
      let label = '';
      if (hop.action === 'on_ramp') label = 'Fiat → Crypto (On-Ramp)';
      else if (hop.action === 'chain_transfer') label = 'L2 Settlement';
      else label = 'Crypto → Fiat (Off-Ramp)';

      const providerStr = hop.provider || hop.chain;
      const details = `${hop.input_amount} ${hop.input_currency} → ${hop.output_amount} ${hop.output_currency}`;
      const timeStr = `Est: ${hop.estimated_seconds}s`;
      const feeLine = `<div style="margin-top:5px; font-size:0.8rem; color:#ffb300;">Fee: $${hop.fee_usd.toFixed(4)}</div>`;
      
      addTimelineNode(label, providerStr.replace('_', ' '), timeStr, iconColor, details + feeLine, `hop-${idx}`);
    });

    addTimelineNode('Local Disbursement', 'Recipient Bank', '', 'var(--text-secondary)', 'Pending credit...', 'disburse-step');

    switchView(viewDashboard, viewFlow);
    runExecutionSequence(currentOptimalRoute);
  });

  function addTimelineNode(title, subtitle, timeStr, iconColor, details, id) {
    const hopDiv = document.createElement('div');
    hopDiv.className = 'hop-node';
    hopDiv.id = id;
    hopDiv.innerHTML = `
      <div class="hop-icon" style="border-color: ${iconColor};"></div>
      <div class="hop-content">
        <div class="hop-title">
          <span>${title}</span>
          <span class="hop-provider">${subtitle.toUpperCase()}</span>
        </div>
        <div class="hop-details" style="display:block;">
          <div style="display:flex; justify-content:space-between;">
             <span>${details}</span>
             <span style="color:var(--text-secondary)">${timeStr}</span>
          </div>
        </div>
      </div>
    `;
    executionTimeline.appendChild(hopDiv);
  }

  async function runExecutionSequence(route) {
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    const nodes = executionTimeline.querySelectorAll('.hop-node');
    
    for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        node.classList.add('active-step');
        
        let waitTime = 1200; 
        if (i > 0 && i < nodes.length - 1) {
            waitTime = Math.min(route.hops[i - 1].estimated_seconds * 1000 * 0.3, 2500); 
        }
        await sleep(waitTime);
        
        node.classList.remove('active-step');
        node.classList.add('completed-step');
        
        const icon = node.querySelector('.hop-icon');
        icon.style.borderColor = 'var(--success)';
        icon.style.background = 'var(--success)';
        icon.style.boxShadow = '0 0 10px var(--success)';
        
        if (i === 0) node.querySelector('.hop-details span').innerHTML = 'Cleared (FATF Travel Rule verified)';
        if (i === nodes.length - 1) {
            const destVal = new Intl.NumberFormat('en-US', { style: 'currency', currency: route.destination_currency }).format(route.destination_amount);
            node.querySelector('.hop-details span').innerHTML = `<b>${destVal}</b> Credited to user account.`;
        }
    }
    
    await sleep(500);
    flowSuccess.style.display = 'block';

    // Save to history
    route.date = new Date().toISOString();
    route.recipientBank = document.getElementById('recipient_bank').value;
    const history = JSON.parse(localStorage.getItem('sb_history') || '[]');
    history.unshift(route);
    localStorage.setItem('sb_history', JSON.stringify(history));
  }

  // --- RETURN TO DASHBOARD ---
  finishBtn.addEventListener('click', () => {
    // Reset Form
    flowSuccess.style.display = 'none';
    quoteResults.style.opacity = '0.5';
    quoteResults.style.pointerEvents = 'none';
    sendMoneyBtn.style.display = 'none';
    quoteResults.querySelector('.status-badge').textContent = 'Pending...';
    quoteResults.querySelector('.status-badge').style.background = 'rgba(255,255,255,0.1)';
    quoteResults.querySelector('.status-badge').style.color = '#fff';
    
    // Switch Views
    switchView(viewFlow, viewDashboard);
    
    // Auto switch to history tab to show the new receipt!
    tabHistory.click();
  });

  // --- RENDER HISTORY ---
  function renderHistory() {
    const history = JSON.parse(localStorage.getItem('sb_history') || '[]');
    if(history.length === 0) {
      historyList.innerHTML = `<div style="text-align:center; padding: 2rem; color: var(--text-secondary);">No past transactions found.</div>`;
      return;
    }

    historyList.innerHTML = history.map((tx, index) => {
      const d = new Date(tx.date);
      const dateStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
      
      const formatFiatType = (cur) => new Intl.NumberFormat('en-US', { style: 'currency', currency: cur }).format;
      const sent = formatFiatType(tx.source_currency)(tx.source_amount);
      const rec = formatFiatType(tx.destination_currency)(tx.destination_amount);
      
      let feesHtml = '';
      tx.hops.forEach(h => {
        let label = h.action === 'on_ramp' ? 'On-Ramp Fee' : (h.action === 'chain_transfer' ? 'Network Gas' : 'Off-Ramp Fee');
        feesHtml += `<div class="fee-row"><span>${label} (${h.provider || h.chain.replace('_',' ')})</span><span>$${h.fee_usd.toFixed(4)}</span></div>`;
      });

      // Show hidden charges savings vs trad bank (trad bank ~ 3-5%)
      const tradBankFee = tx.source_amount * 0.05;

      return `
        <div class="history-item">
          <div class="history-summary" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none'">
            <div>
              <div class="history-date">${dateStr} • To: ${tx.recipientBank}</div>
              <div class="history-amount">${sent} <span style="color:var(--text-secondary); font-size:0.9rem;">→</span> <span class="history-dest">${rec}</span></div>
            </div>
            <div class="history-status">Completed</div>
          </div>
          <div class="history-fee-details" style="display:none;">
            <p style="margin-bottom:1rem; font-weight:600; color:var(--accent-blue);">Cost Breakdown (100% Transparent)</p>
            ${feesHtml}
            <div class="fee-row" style="margin-top:0.5rem; border-top:1px solid rgba(255,255,255,0.1); padding-top:0.5rem; font-weight:bold; color:#fff;">
              <span>Total Fees</span>
              <span>$${tx.total_fee_usd.toFixed(2)} (${tx.total_fee_percent.toFixed(2)}%)</span>
            </div>
            
            <div class="trad-bank-compare">
              <span>Traditional Bank "Hidden" FX Spread (5%)</span>
              <span class="bad">-$${tradBankFee.toFixed(2)}</span>
            </div>
            <div class="trad-bank-compare" style="margin-top: 0.5rem; border-top: none; padding-top:0;">
              <span>Amount Saved</span>
              <span class="good">+$${(tradBankFee - tx.total_fee_usd).toFixed(2)}</span>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // --- RENDER MARKET CHART ---
  let fxChartInstance = null;
  
  function renderChart() {
    const ctx = document.getElementById('fxChart');
    if (!ctx) return;
    
    const currency = document.getElementById('chart_currency').value;
    
    // Generate dummy 5-day history data
    const d = new Date();
    const labels = [];
    for(let i=4; i>=0; i--) {
      const past = new Date(d);
      past.setDate(past.getDate() - i);
      labels.push(past.toLocaleDateString('en-US', {weekday: 'short', month: 'short', day: 'numeric'}));
    }
    
    const datasets = {
      'INR': [84.10, 84.25, 84.20, 84.45, 84.50],
      'PHP': [55.80, 56.00, 55.95, 56.10, 56.20],
      'NGN': [1520, 1540, 1545, 1530, 1550]
    };
    
    const data = datasets[currency];

    if (fxChartInstance) {
      fxChartInstance.destroy();
    }

    fxChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: `USD to ${currency}`,
          data: data,
          borderColor: '#00d2ff',
          backgroundColor: 'rgba(0, 210, 255, 0.1)',
          borderWidth: 3,
          pointBackgroundColor: '#7a28cb',
          pointBorderColor: '#fff',
          pointRadius: 6,
          pointHoverRadius: 8,
          fill: true,
          tension: 0.4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(23, 25, 35, 0.9)',
            titleFont: { size: 14, family: 'Outfit' },
            bodyFont: { size: 14, family: 'Outfit' },
            padding: 12,
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1
          }
        },
        scales: {
          y: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#a0aab2', font: {family: 'Outfit'} }
          },
          x: {
            grid: { display: false },
            ticks: { color: '#a0aab2', font: {family: 'Outfit'} }
          }
        }
      }
    });
  }

  document.getElementById('chart_currency').addEventListener('change', renderChart);
});
