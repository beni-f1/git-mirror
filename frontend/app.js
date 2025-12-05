// Git Mirror Frontend Application

const API_BASE = '/api';

// State
let repoPairs = [];
let globalConfig = {};
let currentUser = null;
let authToken = null;
let users = [];

// ==================== Authentication ====================

function getStoredToken() {
    return localStorage.getItem('auth_token');
}

function setStoredToken(token) {
    if (token) {
        localStorage.setItem('auth_token', token);
    } else {
        localStorage.removeItem('auth_token');
    }
}

async function checkAuth() {
    const token = getStoredToken();
    if (!token) {
        showLoginPage();
        return false;
    }
    
    authToken = token;
    
    try {
        currentUser = await apiCall('/auth/me');
        showApp();
        return true;
    } catch (error) {
        console.error('Auth check failed:', error);
        setStoredToken(null);
        showLoginPage();
        return false;
    }
}

function showLoginPage() {
    document.getElementById('login-page').classList.remove('d-none');
    document.getElementById('app-container').classList.add('d-none');
}

function showApp() {
    document.getElementById('login-page').classList.add('d-none');
    document.getElementById('app-container').classList.remove('d-none');
    
    // Update user info in sidebar
    updateUserDisplay();
    
    // Update UI based on role
    updateRoleBasedUI();
    
    // Initialize page from URL hash
    initFromHash();
}

function updateUserDisplay() {
    if (!currentUser) return;
    
    const displayName = currentUser.full_name || currentUser.username;
    const initials = displayName.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
    
    document.getElementById('user-avatar').textContent = initials;
    document.getElementById('user-display-name').textContent = displayName;
    document.getElementById('user-role').textContent = currentUser.role;
}

function updateRoleBasedUI() {
    const role = currentUser?.role || 'view';
    const isAdmin = role === 'admin';
    const canEdit = role === 'admin' || role === 'edit';
    
    // Show/hide admin navigation
    document.getElementById('admin-nav').classList.toggle('d-none', !isAdmin);
    
    // Show/hide edit-only elements
    document.querySelectorAll('.edit-only').forEach(el => {
        el.classList.toggle('d-none', !canEdit);
    });
    
    // Show/hide admin-only elements
    document.querySelectorAll('.admin-only').forEach(el => {
        el.classList.toggle('d-none', !isAdmin);
    });
}

// Login form handler
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    const errorDiv = document.getElementById('login-error');
    
    errorDiv.style.display = 'none';
    
    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Login failed');
        }
        
        const data = await response.json();
        authToken = data.token;
        currentUser = data.user;
        setStoredToken(data.token);
        
        showApp();
    } catch (error) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
    }
});

async function logout() {
    try {
        await apiCall('/auth/logout', 'POST');
    } catch (error) {
        console.error('Logout error:', error);
    }
    
    authToken = null;
    currentUser = null;
    setStoredToken(null);
    showLoginPage();
    
    // Clear form
    document.getElementById('login-form').reset();
}

// ==================== Navigation ====================

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = e.currentTarget.dataset.page;
        navigateTo(page);
    });
});

function navigateTo(page, updateHash = true) {
    // Check permissions
    const role = currentUser?.role || 'view';
    if (page === 'users' && role !== 'admin') {
        showToast('Access denied', 'danger');
        return;
    }
    
    // Update URL hash
    if (updateHash) {
        window.location.hash = page;
    }
    
    // Update nav
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const navLink = document.querySelector(`[data-page="${page}"]`);
    if (navLink) navLink.classList.add('active');
    
    // Update pages
    document.querySelectorAll('.page').forEach(p => p.classList.add('d-none'));
    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.remove('d-none');
    
    // Load data for page
    if (page === 'dashboard') loadDashboard();
    if (page === 'repos') loadRepoPairs();
    if (page === 'settings') loadSettings();
    if (page === 'users') loadUsers();
}

// Handle browser back/forward buttons
window.addEventListener('hashchange', () => {
    const page = window.location.hash.slice(1) || 'dashboard';
    const validPages = ['dashboard', 'repos', 'settings', 'users'];
    if (validPages.includes(page)) {
        navigateTo(page, false);
    }
});

// Initialize page from URL hash on load
function initFromHash() {
    const page = window.location.hash.slice(1) || 'dashboard';
    const validPages = ['dashboard', 'repos', 'settings'];
    if (currentUser?.role === 'admin') {
        validPages.push('users');
    }
    
    if (validPages.includes(page)) {
        navigateTo(page, false);
    } else {
        navigateTo('dashboard', true);
    }
}

// ==================== Toast Notifications ====================

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast show align-items-center text-bg-${type} border-0`;
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    container.appendChild(toast);
    
    setTimeout(() => toast.remove(), 5000);
}

// ==================== API Calls ====================

async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'include'
    };
    
    // Add auth token if available
    if (authToken) {
        options.headers['Authorization'] = `Bearer ${authToken}`;
    }
    
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    
    if (response.status === 401) {
        // Token expired or invalid
        setStoredToken(null);
        showLoginPage();
        throw new Error('Session expired. Please login again.');
    }
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'API Error');
    }
    
    return response.json();
}

// ==================== Dashboard ====================

async function loadDashboard() {
    try {
        const stats = await apiCall('/stats');
        document.getElementById('stat-total').textContent = stats.total_pairs;
        document.getElementById('stat-active').textContent = stats.active_pairs;
        document.getElementById('stat-syncs').textContent = stats.total_syncs;
        
        const statusIcon = stats.scheduler_running 
            ? '<i class="bi bi-circle-fill text-success"></i>' 
            : '<i class="bi bi-circle-fill text-danger"></i>';
        document.getElementById('stat-status').innerHTML = statusIcon;
        
        // Load recent activity
        await loadRecentActivity();
    } catch (error) {
        showToast('Failed to load dashboard: ' + error.message, 'danger');
    }
}

async function loadRecentActivity() {
    try {
        const pairs = await apiCall('/repo-pairs');
        const activityContainer = document.getElementById('recent-activity');
        
        if (pairs.length === 0) {
            activityContainer.innerHTML = '<p class="text-muted">No repository pairs configured</p>';
            return;
        }
        
        // Get recent syncs from all pairs
        const activities = pairs
            .filter(p => p.last_sync)
            .sort((a, b) => new Date(b.last_sync) - new Date(a.last_sync))
            .slice(0, 5);
        
        if (activities.length === 0) {
            activityContainer.innerHTML = '<p class="text-muted">No recent sync activity</p>';
            return;
        }
        
        activityContainer.innerHTML = activities.map(pair => `
            <div class="log-entry">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${pair.name}</strong>
                        <span class="status-badge ${getStatusClass(pair.last_sync_status)} ms-2">
                            ${pair.last_sync_status || 'pending'}
                        </span>
                    </div>
                    <span class="log-time">${formatDate(pair.last_sync)}</span>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load recent activity:', error);
    }
}

// ==================== Repository Pairs ====================

async function loadRepoPairs() {
    try {
        repoPairs = await apiCall('/repo-pairs');
        renderRepoPairs();
    } catch (error) {
        showToast('Failed to load repository pairs: ' + error.message, 'danger');
    }
}

function renderRepoPairs() {
    const tbody = document.getElementById('repos-table-body');
    const canEdit = currentUser?.role === 'admin' || currentUser?.role === 'edit';
    
    if (repoPairs.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center py-4 text-muted">
                    No repository pairs configured
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = repoPairs.map(pair => `
        <tr>
            <td><strong>${pair.name}</strong></td>
            <td><span class="repo-url" title="${pair.source_url}">${pair.source_url}</span></td>
            <td><span class="repo-url" title="${pair.destination_url}">${pair.destination_url}</span></td>
            <td>${pair.sync_interval_minutes} min</td>
            <td>${pair.last_sync ? formatDate(pair.last_sync) : 'Never'}</td>
            <td>
                ${pair.enabled 
                    ? `<span class="status-badge ${getStatusClass(pair.last_sync_status)}">${pair.last_sync_status || 'pending'}</span>`
                    : '<span class="status-badge status-disabled">disabled</span>'
                }
            </td>
            <td>
                ${canEdit ? `
                    <button class="action-btn sync me-1" onclick="triggerSync('${pair.id}')" title="Sync Now">
                        <i class="bi bi-arrow-repeat"></i>
                    </button>
                ` : ''}
                <button class="action-btn me-1" onclick="showLogs('${pair.id}')" title="View Logs">
                    <i class="bi bi-list-ul"></i>
                </button>
                ${canEdit ? `
                    <button class="action-btn me-1" onclick="editRepoPair('${pair.id}')" title="Edit">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="action-btn delete" onclick="deleteRepoPair('${pair.id}')" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                ` : ''}
            </td>
        </tr>
    `).join('');
}

function getStatusClass(status) {
    switch (status) {
        case 'success': return 'status-success';
        case 'error': return 'status-error';
        default: return 'status-pending';
    }
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString();
}

// Add/Edit Repo Form
const repoModal = new bootstrap.Modal(document.getElementById('addRepoModal'));

document.getElementById('addRepoModal').addEventListener('hidden.bs.modal', () => {
    resetRepoForm();
});

function resetRepoForm() {
    document.getElementById('repo-form').reset();
    document.getElementById('repo-id').value = '';
    document.getElementById('repoModalTitle').innerHTML = '<i class="bi bi-plus-circle me-2" style="color: #6366f1;"></i>Add Repository Pair';
    document.getElementById('repo-enabled').checked = true;
    document.getElementById('repo-sync-tags').checked = true;
    document.getElementById('repo-interval').value = '60';
    document.getElementById('repo-branches').value = '*';
}

function editRepoPair(id) {
    const pair = repoPairs.find(p => p.id === id);
    if (!pair) return;
    
    document.getElementById('repo-id').value = pair.id;
    document.getElementById('repo-name').value = pair.name;
    document.getElementById('repo-source-url').value = pair.source_url;
    document.getElementById('repo-dest-url').value = pair.destination_url;
    document.getElementById('repo-interval').value = pair.sync_interval_minutes;
    document.getElementById('repo-branches').value = (pair.sync_branches || ['*']).join(', ');
    document.getElementById('repo-sync-tags').checked = pair.sync_tags !== false;
    document.getElementById('repo-enabled').checked = pair.enabled !== false;
    
    // Fill credentials if present
    if (pair.source_credentials) {
        document.getElementById('source-username').value = pair.source_credentials.username || '';
        document.getElementById('source-password').value = pair.source_credentials.password || '';
        document.getElementById('source-ssh-key').value = pair.source_credentials.ssh_key || '';
    }
    if (pair.destination_credentials) {
        document.getElementById('dest-username').value = pair.destination_credentials.username || '';
        document.getElementById('dest-password').value = pair.destination_credentials.password || '';
        document.getElementById('dest-ssh-key').value = pair.destination_credentials.ssh_key || '';
    }
    
    document.getElementById('repoModalTitle').innerHTML = '<i class="bi bi-pencil me-2" style="color: #6366f1;"></i>Edit Repository Pair';
    repoModal.show();
}

document.getElementById('save-repo-btn').addEventListener('click', async () => {
    const id = document.getElementById('repo-id').value;
    const branches = document.getElementById('repo-branches').value
        .split(',')
        .map(b => b.trim())
        .filter(b => b);
    
    const data = {
        name: document.getElementById('repo-name').value,
        source_url: document.getElementById('repo-source-url').value,
        destination_url: document.getElementById('repo-dest-url').value,
        sync_interval_minutes: parseInt(document.getElementById('repo-interval').value),
        sync_branches: branches.length ? branches : ['*'],
        sync_tags: document.getElementById('repo-sync-tags').checked,
        enabled: document.getElementById('repo-enabled').checked,
        source_credentials: {
            username: document.getElementById('source-username').value || null,
            password: document.getElementById('source-password').value || null,
            ssh_key: document.getElementById('source-ssh-key').value || null
        },
        destination_credentials: {
            username: document.getElementById('dest-username').value || null,
            password: document.getElementById('dest-password').value || null,
            ssh_key: document.getElementById('dest-ssh-key').value || null
        }
    };
    
    // Clean up empty credentials
    if (!data.source_credentials.username && !data.source_credentials.password && !data.source_credentials.ssh_key) {
        data.source_credentials = null;
    }
    if (!data.destination_credentials.username && !data.destination_credentials.password && !data.destination_credentials.ssh_key) {
        data.destination_credentials = null;
    }
    
    try {
        if (id) {
            await apiCall(`/repo-pairs/${id}`, 'PUT', data);
            showToast('Repository pair updated successfully');
        } else {
            await apiCall('/repo-pairs', 'POST', data);
            showToast('Repository pair created successfully');
        }
        
        repoModal.hide();
        loadRepoPairs();
    } catch (error) {
        showToast('Failed to save: ' + error.message, 'danger');
    }
});

async function deleteRepoPair(id) {
    if (!confirm('Are you sure you want to delete this repository pair?')) return;
    
    try {
        await apiCall(`/repo-pairs/${id}`, 'DELETE');
        showToast('Repository pair deleted');
        loadRepoPairs();
    } catch (error) {
        showToast('Failed to delete: ' + error.message, 'danger');
    }
}

async function triggerSync(id) {
    try {
        await apiCall(`/repo-pairs/${id}/sync`, 'POST');
        showToast('Sync triggered successfully');
        
        // Refresh after a delay
        setTimeout(loadRepoPairs, 2000);
    } catch (error) {
        showToast('Failed to trigger sync: ' + error.message, 'danger');
    }
}

// ==================== Logs ====================

const logsModal = new bootstrap.Modal(document.getElementById('logsModal'));

async function showLogs(id) {
    const container = document.getElementById('logs-container');
    container.innerHTML = '<p class="text-muted">Loading logs...</p>';
    logsModal.show();
    
    try {
        const logs = await apiCall(`/repo-pairs/${id}/logs`);
        
        if (logs.length === 0) {
            container.innerHTML = '<p class="text-muted">No sync logs available</p>';
            return;
        }
        
        container.innerHTML = logs.map(log => `
            <div class="log-entry">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="status-badge ${getStatusClass(log.status)}">${log.status}</span>
                    <span class="log-time">${formatDate(log.timestamp)}</span>
                </div>
                <div class="small">
                    ${log.message || log.error || 'No details'}
                    ${log.duration_seconds ? `<br><span class="text-muted">Duration: ${log.duration_seconds.toFixed(1)}s</span>` : ''}
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<p class="text-danger">Failed to load logs: ${error.message}</p>`;
    }
}

// ==================== Settings ====================

async function loadSettings() {
    try {
        globalConfig = await apiCall('/config');
        document.getElementById('config-interval').value = globalConfig.default_sync_interval_minutes;
        document.getElementById('config-concurrent').value = globalConfig.max_concurrent_syncs;
        document.getElementById('config-retry').checked = globalConfig.retry_on_failure;
        document.getElementById('config-retry-count').value = globalConfig.retry_count;
    } catch (error) {
        showToast('Failed to load settings: ' + error.message, 'danger');
    }
}

document.getElementById('settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const config = {
        default_sync_interval_minutes: parseInt(document.getElementById('config-interval').value),
        max_concurrent_syncs: parseInt(document.getElementById('config-concurrent').value),
        retry_on_failure: document.getElementById('config-retry').checked,
        retry_count: parseInt(document.getElementById('config-retry-count').value)
    };
    
    try {
        await apiCall('/config', 'PUT', config);
        showToast('Settings saved successfully');
    } catch (error) {
        showToast('Failed to save settings: ' + error.message, 'danger');
    }
});

// ==================== User Management ====================

async function loadUsers() {
    try {
        users = await apiCall('/users');
        renderUsers();
    } catch (error) {
        showToast('Failed to load users: ' + error.message, 'danger');
    }
}

function renderUsers() {
    const tbody = document.getElementById('users-table-body');
    
    if (users.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center py-4 text-muted">
                    No users found
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = users.map(user => `
        <tr>
            <td><strong>${user.username}</strong></td>
            <td>${user.full_name || '-'}</td>
            <td>${user.email || '-'}</td>
            <td><span class="badge bg-${getRoleBadgeClass(user.role)}">${user.role}</span></td>
            <td>
                ${user.is_active 
                    ? '<span class="status-badge status-success">Active</span>'
                    : '<span class="status-badge status-disabled">Inactive</span>'
                }
            </td>
            <td>${user.last_login ? formatDate(user.last_login) : 'Never'}</td>
            <td>
                <button class="action-btn me-1" onclick="editUser('${user.id}')" title="Edit">
                    <i class="bi bi-pencil"></i>
                </button>
                ${user.id !== currentUser.id ? `
                    <button class="action-btn delete" onclick="deleteUser('${user.id}')" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                ` : ''}
            </td>
        </tr>
    `).join('');
}

function getRoleBadgeClass(role) {
    switch (role) {
        case 'admin': return 'danger';
        case 'edit': return 'warning';
        default: return 'secondary';
    }
}

// Add/Edit User Form
const userModal = new bootstrap.Modal(document.getElementById('addUserModal'));

document.getElementById('addUserModal').addEventListener('hidden.bs.modal', () => {
    resetUserForm();
});

function resetUserForm() {
    document.getElementById('user-form').reset();
    document.getElementById('user-id').value = '';
    document.getElementById('userModalTitle').innerHTML = '<i class="bi bi-person-plus me-2" style="color: #6366f1;"></i>Add User';
    document.getElementById('user-password').required = true;
    document.getElementById('password-help').textContent = 'Must be at least 4 characters';
    document.getElementById('user-active').checked = true;
    document.getElementById('user-role').value = 'view';
}

function editUser(id) {
    const user = users.find(u => u.id === id);
    if (!user) return;
    
    document.getElementById('user-id').value = user.id;
    document.getElementById('user-username').value = user.username;
    document.getElementById('user-password').value = '';
    document.getElementById('user-password').required = false;
    document.getElementById('password-help').textContent = 'Leave empty to keep current password';
    document.getElementById('user-fullname').value = user.full_name || '';
    document.getElementById('user-email').value = user.email || '';
    document.getElementById('user-role').value = user.role;
    document.getElementById('user-active').checked = user.is_active;
    
    document.getElementById('userModalTitle').innerHTML = '<i class="bi bi-pencil me-2" style="color: #6366f1;"></i>Edit User';
    userModal.show();
}

document.getElementById('save-user-btn').addEventListener('click', async () => {
    const id = document.getElementById('user-id').value;
    const password = document.getElementById('user-password').value;
    
    const data = {
        username: document.getElementById('user-username').value,
        full_name: document.getElementById('user-fullname').value || null,
        email: document.getElementById('user-email').value || null,
        role: document.getElementById('user-role').value,
        is_active: document.getElementById('user-active').checked
    };
    
    // Only include password if provided
    if (password) {
        data.password = password;
    }
    
    try {
        if (id) {
            await apiCall(`/users/${id}`, 'PUT', data);
            showToast('User updated successfully');
        } else {
            if (!password) {
                showToast('Password is required for new users', 'danger');
                return;
            }
            await apiCall('/users', 'POST', data);
            showToast('User created successfully');
        }
        
        userModal.hide();
        loadUsers();
    } catch (error) {
        showToast('Failed to save user: ' + error.message, 'danger');
    }
});

async function deleteUser(id) {
    if (!confirm('Are you sure you want to delete this user?')) return;
    
    try {
        await apiCall(`/users/${id}`, 'DELETE');
        showToast('User deleted successfully');
        loadUsers();
    } catch (error) {
        showToast('Failed to delete user: ' + error.message, 'danger');
    }
}

// ==================== Change Password ====================

const passwordModal = new bootstrap.Modal(document.getElementById('changePasswordModal'));

document.getElementById('change-password-btn').addEventListener('click', async () => {
    const currentPassword = document.getElementById('current-password').value;
    const newPassword = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;
    
    if (newPassword !== confirmPassword) {
        showToast('New passwords do not match', 'danger');
        return;
    }
    
    try {
        await apiCall('/auth/password', 'PUT', {
            current_password: currentPassword,
            new_password: newPassword
        });
        
        showToast('Password changed successfully');
        passwordModal.hide();
        document.getElementById('password-form').reset();
    } catch (error) {
        showToast('Failed to change password: ' + error.message, 'danger');
    }
});

// ==================== Initialization ====================

// Check authentication on page load
checkAuth();

// Auto-refresh dashboard
setInterval(() => {
    if (currentUser && !document.getElementById('page-dashboard').classList.contains('d-none')) {
        loadDashboard();
    }
}, 30000);