const profileAuthHint = document.getElementById('profileAuthHint');
const profileConsent = document.getElementById('profileConsent');
const profileStatus = document.getElementById('profileStatus');
const accessToken = localStorage.getItem('accessToken');

const fields = {
    height_cm: document.getElementById('heightCm'),
    weight_kg: document.getElementById('weightKg'),
    target_weight_kg: document.getElementById('targetWeightKg'),
    age: document.getElementById('age'),
    sex: document.getElementById('sex'),
    activity_level: document.getElementById('activityLevel'),
    health_goal: document.getElementById('healthGoal'),
    meals_per_day: document.getElementById('mealsPerDay'),
    daily_budget: document.getElementById('dailyBudget'),
    allergies: document.getElementById('allergies'),
    dietary_preferences: document.getElementById('dietaryPreferences'),
    disliked_foods: document.getElementById('dislikedFoods'),
    common_ingredients: document.getElementById('commonIngredients'),
};

function setStatus(message, error = false) {
    profileStatus.textContent = message;
    profileStatus.className = `knowledge-status${error ? ' error' : ''}`;
}

function authHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    return headers;
}

async function apiJson(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: { ...authHeaders(), ...(options.headers || {}) },
    });
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
    return data;
}

function listValue(text) {
    return text.split(',').map((item) => item.trim()).filter(Boolean);
}

function setNumber(element, value) {
    element.value = value === null || value === undefined ? '' : value;
}

function fillProfile(data) {
    const profile = data.profile || {};
    profileConsent.checked = Boolean(data.consent_granted);
    Object.entries(fields).forEach(([name, element]) => {
        const value = profile[name];
        if (Array.isArray(value)) element.value = value.join(', ');
        else if (element.type === 'number') setNumber(element, value);
        else element.value = value || '';
    });
    profileAuthHint.textContent = data.consent_granted
        ? `已授权使用个人档案 · 版本 ${data.version}`
        : '尚未授权使用个人档案';
}

function payload() {
    const data = {};
    const listFields = new Set(['allergies', 'dietary_preferences', 'disliked_foods', 'common_ingredients']);
    Object.entries(fields).forEach(([name, element]) => {
        if (listFields.has(name)) {
            data[name] = listValue(element.value);
        } else if (element.type === 'number') {
            data[name] = element.value === '' ? null : Number(element.value);
        } else {
            data[name] = element.value || null;
        }
    });
    data.consent_granted = profileConsent.checked;
    return data;
}

async function loadProfile() {
    if (!accessToken) {
        profileAuthHint.textContent = '请先返回聊天页面注册或登录，再编辑个人档案。';
        document.getElementById('saveProfile').disabled = true;
        document.getElementById('deleteProfile').disabled = true;
        return;
    }
    try {
        fillProfile(await apiJson('/me/profile'));
    } catch (error) {
        setStatus(error.message, true);
    }
}

async function saveProfile() {
    if (!profileConsent.checked) {
        setStatus('请先勾选授权，或使用“清空个人档案”撤销授权。', true);
        return;
    }
    try {
        fillProfile(await apiJson('/me/profile', { method: 'PUT', body: JSON.stringify(payload()) }));
        setStatus('个人档案已保存');
    } catch (error) {
        setStatus(error.message, true);
    }
}

async function deleteProfile() {
    if (!window.confirm('确定清空个人档案并撤销使用授权吗？')) return;
    try {
        fillProfile(await apiJson('/me/profile', { method: 'DELETE' }));
        setStatus('个人档案已清空');
    } catch (error) {
        setStatus(error.message, true);
    }
}

document.getElementById('saveProfile').addEventListener('click', saveProfile);
document.getElementById('deleteProfile').addEventListener('click', deleteProfile);
loadProfile();
