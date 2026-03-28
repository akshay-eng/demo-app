const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8000'
    : '';

function showSection(sectionId) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(sectionId).classList.add('active');
    event.target.classList.add('active');

    if (sectionId === 'dashboard') loadDashboard();
    if (sectionId === 'patients') loadPatients();
    if (sectionId === 'orders') loadOrders();
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    setTimeout(() => { toast.className = 'toast'; }, 3000);
}

async function loadDashboard() {
    try {
        const [healthRes, statsRes] = await Promise.all([
            fetch(`${API_BASE}/health`),
            fetch(`${API_BASE}/api/v1/stats`)
        ]);
        const health = await healthRes.json();
        const stats = await statsRes.json();

        const statusEl = document.getElementById('health-status');
        statusEl.textContent = `System: ${health.status} | Database: ${health.database}`;
        statusEl.className = `health-status ${health.status === 'healthy' ? 'healthy' : 'unhealthy'}`;

        document.getElementById('stat-patients').textContent = stats.total_patients;
        document.getElementById('stat-orders').textContent = stats.total_orders;
        document.getElementById('stat-pending').textContent = stats.pending_orders;
        document.getElementById('stat-completed').textContent = stats.completed_orders;
    } catch (err) {
        document.getElementById('health-status').textContent = 'System: Unreachable';
        document.getElementById('health-status').className = 'health-status unhealthy';
    }
}

async function loadPatients() {
    try {
        const res = await fetch(`${API_BASE}/api/v1/patients`);
        const data = await res.json();
        const tbody = document.querySelector('#patients-table tbody');
        tbody.innerHTML = data.patients.map(p => `
            <tr>
                <td><code>${p._id.substring(0, 8)}...</code></td>
                <td>${p.first_name} ${p.last_name}</td>
                <td>${p.date_of_birth || '-'}</td>
                <td>${p.email || '-'}</td>
                <td>${p.phone || '-'}</td>
            </tr>
        `).join('');
    } catch (err) {
        showToast('Failed to load patients', 'error');
    }
}

async function createPatient(e) {
    e.preventDefault();
    const patient = {
        first_name: document.getElementById('first_name').value,
        last_name: document.getElementById('last_name').value,
        date_of_birth: document.getElementById('dob').value,
        email: document.getElementById('email').value,
        phone: document.getElementById('phone').value,
    };
    try {
        const res = await fetch(`${API_BASE}/api/v1/patients`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patient)
        });
        if (res.ok) {
            showToast('Patient registered successfully');
            e.target.reset();
            loadPatients();
        } else {
            showToast('Failed to register patient', 'error');
        }
    } catch (err) {
        showToast('Error connecting to server', 'error');
    }
}

async function loadOrders() {
    try {
        const res = await fetch(`${API_BASE}/api/v1/orders`);
        const data = await res.json();
        const tbody = document.querySelector('#orders-table tbody');
        tbody.innerHTML = data.orders.map(o => `
            <tr>
                <td><code>${o._id.substring(0, 8)}...</code></td>
                <td><code>${o.patient_id.substring(0, 8)}...</code></td>
                <td>${o.test_type}</td>
                <td class="priority-${o.priority}">${o.priority.toUpperCase()}</td>
                <td class="status-${o.status}">${o.status.toUpperCase()}</td>
                <td>${o.ordering_physician}</td>
            </tr>
        `).join('');
    } catch (err) {
        showToast('Failed to load orders', 'error');
    }
}

async function createOrder(e) {
    e.preventDefault();
    const order = {
        patient_id: document.getElementById('order_patient_id').value,
        test_type: document.getElementById('test_type').value,
        priority: document.getElementById('priority').value,
        ordering_physician: document.getElementById('physician').value,
        notes: document.getElementById('order_notes').value,
    };
    try {
        const res = await fetch(`${API_BASE}/api/v1/orders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(order)
        });
        if (res.ok) {
            showToast('Lab order created');
            e.target.reset();
            loadOrders();
        } else {
            showToast('Failed to create order', 'error');
        }
    } catch (err) {
        showToast('Error connecting to server', 'error');
    }
}

async function createResult(e) {
    e.preventDefault();
    const result = {
        order_id: document.getElementById('result_order_id').value,
        test_name: document.getElementById('test_name').value,
        value: document.getElementById('result_value').value,
        unit: document.getElementById('result_unit').value,
        reference_range: document.getElementById('ref_range').value,
        status: document.getElementById('result_status').value,
    };
    try {
        const res = await fetch(`${API_BASE}/api/v1/results`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(result)
        });
        if (res.ok) {
            showToast('Result recorded');
            e.target.reset();
        } else {
            showToast('Failed to record result', 'error');
        }
    } catch (err) {
        showToast('Error connecting to server', 'error');
    }
}

async function lookupResults() {
    const orderId = document.getElementById('lookup_order_id').value;
    if (!orderId) return;
    try {
        const res = await fetch(`${API_BASE}/api/v1/results/${orderId}`);
        const display = document.getElementById('results-display');
        if (res.ok) {
            const data = await res.json();
            display.innerHTML = data.results.map(r => `
                <div class="result-card">
                    <strong>${r.test_name}</strong>: ${r.value} ${r.unit}
                    <br>Reference: ${r.reference_range} | Status: ${r.status}
                </div>
            `).join('');
        } else {
            display.innerHTML = '<p>No results found for this order.</p>';
        }
    } catch (err) {
        showToast('Error looking up results', 'error');
    }
}

// Load dashboard on page load
loadDashboard();
