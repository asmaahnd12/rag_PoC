// Backend API configuration
const API_BASE_URL = "http://127.0.0.1:8000";

// API Endpoints
const API_ENDPOINTS = {
  register: `${API_BASE_URL}/admin/register`,
  login: `${API_BASE_URL}/login`,
  logout: `${API_BASE_URL}/logout`,

  chat: `${API_BASE_URL}/chat`,
  chatStream: `${API_BASE_URL}/chat/stream`,
  newChat: `${API_BASE_URL}/chat/new`,
  sessions: `${API_BASE_URL}/chat/sessions`,

  user: `${API_BASE_URL}/user`,
  upload: `${API_BASE_URL}/upload`,

  listUsers: `${API_BASE_URL}/admin/users`,
  updateUserAdmin: `${API_BASE_URL}/admin/update-user-admin`,
  updateUsername: `${API_BASE_URL}/admin/update-username`,
  collectionInfo: `${API_BASE_URL}/admin/collection-info`,
  personalities: `${API_BASE_URL}/personalities`,
  adminPersonalities: `${API_BASE_URL}/admin/personalities`,
  userWeeklyStats: `${API_BASE_URL}/admin/user-weekly-stats`,
  userFileDailyTrend: `${API_BASE_URL}/admin/user-file-daily-trend`,
};
