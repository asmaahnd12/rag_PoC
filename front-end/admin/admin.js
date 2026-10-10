const LS_TOKEN = "access_token";
const LS_USER = "username";
const LS_PERSONALITIES_VERSION = "personalities_version";
const LS_ADMIN_LAST_VIEW = "admin_last_view";
const MAX_CUSTOM_PERSONALITIES = 5;

let personalities = [];
let editingId = null;
let adminBackHandler = null;
let pendingPersonalityPayload = null;
let pendingPersonalityId = null;

boot();

async function boot() {
  guardAuth();
  initUserCard();
  bindEvents();
  await loadPersonalities();
  restoreAdminView();
}

function guardAuth() {
  const token = localStorage.getItem(LS_TOKEN);
  if (!token) {
    window.location.href = "/";
    return;
  }

  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    if (payload.role !== "admin") {
      window.location.href = "/chat";
    }
  } catch {
    window.location.href = "/";
  }
}

async function apiRequest(url, options = {}) {
  const token = localStorage.getItem(LS_TOKEN);

  const headers = {
    Authorization: `Bearer ${token}`,
    ...(options.headers || {}),
  };

  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (response.status === 401 || response.status === 403) {
    showToast(
      (data && data.detail) || "Session expirée ou accès refusé",
      "error",
    );
  }

  return { response, data };
}

function notifyPersonalitiesChanged() {
  localStorage.setItem(LS_PERSONALITIES_VERSION, String(Date.now()));
}

function initUserCard() {
  const username = (localStorage.getItem(LS_USER) || "Admin").trim();
  const nameEl = document.getElementById("adminName");
  const avatarEl = document.getElementById("adminAvatar");

  if (nameEl) nameEl.textContent = username;
  if (avatarEl) avatarEl.textContent = makeInitials(username);
}

function makeInitials(name) {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function bindEvents() {
  document.getElementById("logoutBtn").addEventListener("click", handleLogout);

  document.getElementById("modalClose").addEventListener("click", closeModal);
  document.getElementById("modalCancel").addEventListener("click", closeModal);

  document.getElementById("modalOverlay").addEventListener("click", (e) => {
    if (e.target === document.getElementById("modalOverlay")) closeModal();
  });

  document
    .getElementById("uploadConfirmClose")
    .addEventListener("click", closeUploadConfirmModal);
  document
    .getElementById("uploadConfirmCancel")
    .addEventListener("click", closeUploadConfirmModal);
  document
    .getElementById("uploadConfirmProceed")
    .addEventListener("click", handleUploadConfirmProceed);

  document
    .getElementById("uploadConfirmOverlay")
    .addEventListener("click", (e) => {
      if (e.target === document.getElementById("uploadConfirmOverlay")) {
        closeUploadConfirmModal();
      }
    });

  document
    .getElementById("modalSave")
    .addEventListener("click", handleModalSave);

  document
    .getElementById("modalPrompt")
    .addEventListener("input", updateCharCount);

  document
    .getElementById("personalityConfirmClose")
    .addEventListener("click", closePersonalityConfirmModal);
  document
    .getElementById("personalityConfirmCancel")
    .addEventListener("click", closePersonalityConfirmModal);
  document
    .getElementById("personalityConfirmProceed")
    .addEventListener("click", handlePersonalityConfirmProceed);

  document
    .getElementById("personalityConfirmOverlay")
    .addEventListener("click", (e) => {
      if (e.target === document.getElementById("personalityConfirmOverlay")) {
        closePersonalityConfirmModal();
      }
    });

  const manageUsersBtn = document.getElementById("navManageUsers");
  if (manageUsersBtn) {
    manageUsersBtn.addEventListener("click", showUserManagementHub);
  }

  document
    .getElementById("navPersonalities")
    .addEventListener("click", showPersonalitiesView);

  document.getElementById("navUploadFile").addEventListener("click", () => {
    openUploadConfirmModal();
  });

  document
    .getElementById("adminFileUpload")
    .addEventListener("change", handleAdminFileUpload);

  const closeBtn = document.getElementById("adminActionClose");
  if (closeBtn) {
    closeBtn.addEventListener("click", closeAdminActionPanel);
  }

  const backBtn = document.getElementById("adminActionBack");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      if (typeof adminBackHandler === "function") {
        adminBackHandler();
      }
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeModal();
      closePersonalityConfirmModal();
      closeUploadConfirmModal();
      closeAdminActionPanel();
    }
  });
}

function setActiveNav(activeId) {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.remove("active");
  });

  if (!activeId) return;

  const active = document.getElementById(activeId);
  if (active) active.classList.add("active");
}

function showCardsGrid() {
  const header = document.querySelector(".main-header");
  const cardsGrid = document.getElementById("cardsGrid");
  const title = document.querySelector(".main-header h1");
  const subtitle = document.querySelector(".main-header .subtitle");
  const badge = document.getElementById("countBadge");

  if (header) header.style.display = "flex";
  if (cardsGrid) cardsGrid.style.display = "grid";
  if (title) title.textContent = "Gestion des Personnalités IA";
  if (subtitle) subtitle.textContent = "Ensemble des personnalités disponibles";
  if (badge) badge.style.display = "block";
}

function hideCardsGrid() {
  const header = document.querySelector(".main-header");
  const cardsGrid = document.getElementById("cardsGrid");

  if (header) header.style.display = "none";
  if (cardsGrid) cardsGrid.style.display = "none";
}

function showPersonalitiesView() {
  setActiveNav("navPersonalities");
  closeAdminActionPanel();
  setAdminBackAction(null);
  setAdminLastView("personalities");
  renderAll();
  showCardsGrid();
}

function showUserManagementHub() {
  setActiveNav("navManageUsers");
  setAdminBackAction(null);
  setAdminLastView("manage_users");

  openAdminActionPanel(
    "Gestion des utilisateurs",
    `
      <div class="user-hub-grid">
        <button class="user-hub-card" type="button" data-action="search">
          <span class="user-hub-icon">🔍</span>
          <span class="user-hub-title">Chercher un utilisateur</span>
          <span class="user-hub-sub">Trouver un compte par username.</span>
        </button>
        <button class="user-hub-card" type="button" data-action="list">
          <span class="user-hub-icon">📋</span>
          <span class="user-hub-title">Lister les utilisateurs</span>
          <span class="user-hub-sub">Afficher tous les comptes.</span>
        </button>
        <button class="user-hub-card" type="button" data-action="promote">
          <span class="user-hub-icon">🛡️</span>
          <span class="user-hub-title">Mettre admin</span>
          <span class="user-hub-sub">Donner les droits administrateur.</span>
        </button>
        <button class="user-hub-card" type="button" data-action="rename">
          <span class="user-hub-icon">✏️</span>
          <span class="user-hub-title">Modifier username</span>
          <span class="user-hub-sub">Renommer un compte.</span>
        </button>
        <button class="user-hub-card" type="button" data-action="delete">
          <span class="user-hub-icon">🗑️</span>
          <span class="user-hub-title">Supprimer utilisateur</span>
          <span class="user-hub-sub">Retirer un compte du système.</span>
        </button>
        <button class="user-hub-card" type="button" data-action="register">
          <span class="user-hub-icon">➕</span>
          <span class="user-hub-title">Créer un utilisateur</span>
          <span class="user-hub-sub">Enregistrer un nouveau compte.</span>
        </button>
      </div>
    `,
  );

  const actions = {
    search: showSearchUserPanel,
    list: handleListUsers,
    promote: showUpdateAdminPanel,
    rename: showUpdateUsernamePanel,
    delete: showDeleteUserPanel,
    register: showRegisterUserPanel,
  };

  document.querySelectorAll(".user-hub-card").forEach((card) => {
    card.addEventListener("click", () => {
      const action = card.dataset.action;
      const handler = actions[action];
      if (handler) handler();
    });
  });
}

function showAdminLanding() {
  setActiveNav(null);
  closeAdminActionPanel();
  setAdminBackAction(null);

  const header = document.querySelector(".main-header");
  const cardsGrid = document.getElementById("cardsGrid");
  const title = document.querySelector(".main-header h1");
  const subtitle = document.querySelector(".main-header .subtitle");
  const badge = document.getElementById("countBadge");

  if (header) header.style.display = "flex";
  if (cardsGrid) cardsGrid.style.display = "none";
  if (title) title.textContent = "Panneau Administrateur";
  if (subtitle) subtitle.textContent = "Choisissez une rubrique";
  if (badge) badge.style.display = "none";
}

function setAdminLastView(viewKey) {
  if (!viewKey) return;
  localStorage.setItem(LS_ADMIN_LAST_VIEW, viewKey);
}

function restoreAdminView() {
  const viewKey = localStorage.getItem(LS_ADMIN_LAST_VIEW);
  if (!viewKey) {
    showAdminLanding();
    return;
  }

  switch (viewKey) {
    case "personalities":
      showPersonalitiesView();
      return;
    case "manage_users":
      showUserManagementHub();
      return;
    case "manage_users:search":
      showSearchUserPanel();
      return;
    case "manage_users:list":
      handleListUsers();
      return;
    case "manage_users:promote":
      showUpdateAdminPanel();
      return;
    case "manage_users:rename":
      showUpdateUsernamePanel();
      return;
    case "manage_users:delete":
      showDeleteUserPanel();
      return;
    case "manage_users:register":
      showRegisterUserPanel();
      return;
    default:
      showAdminLanding();
  }
}

function setAdminBackAction(handler) {
  const backBtn = document.getElementById("adminActionBack");
  adminBackHandler = handler || null;

  if (!backBtn) return;

  if (adminBackHandler) {
    backBtn.classList.remove("is-hidden");
  } else {
    backBtn.classList.add("is-hidden");
  }
}

function openAdminActionPanel(title, html) {
  hideCardsGrid();

  const panel = document.getElementById("adminActionPanel");
  const titleEl = document.getElementById("adminActionTitle");
  const content = document.getElementById("adminActionContent");
  const result = document.getElementById("adminActionResult");

  titleEl.textContent = title;
  content.innerHTML = html;
  result.innerHTML = "";
  panel.classList.add("open");
}

function closeAdminActionPanel() {
  const panel = document.getElementById("adminActionPanel");
  const content = document.getElementById("adminActionContent");
  const result = document.getElementById("adminActionResult");

  if (panel) panel.classList.remove("open");
  if (content) content.innerHTML = "";
  if (result) result.innerHTML = "";
  setAdminBackAction(null);
}

async function handleLogout() {
  const token = localStorage.getItem(LS_TOKEN);

  if (token) {
    try {
      await fetch(API_ENDPOINTS.logout, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
    } catch {}
  }

  localStorage.removeItem(LS_TOKEN);
  localStorage.removeItem(LS_USER);
  window.location.href = "/";
}

async function loadPersonalities() {
  const { response, data } = await apiRequest(API_ENDPOINTS.personalities, {
    method: "GET",
  });

  if (!response.ok) {
    console.error("Failed to load personalities:", data);
    showToast(
      (data && data.detail) || "Impossible de charger les personnalités",
      "error",
    );
    personalities = [];
    return;
  }

  personalities = Array.isArray(data) ? data : [];
}

function getCustomCount() {
  return personalities.filter((p) => Number(p.id) !== 0).length;
}

function renderAll() {
  const grid = document.getElementById("cardsGrid");
  if (!grid) return;

  grid.innerHTML = "";

  personalities.forEach((p) => {
    grid.appendChild(buildCard(p));
  });

  grid.appendChild(buildAddCard());
  updateBadge();
}

function updateBadge() {
  const badge = document.getElementById("countBadge");
  if (!badge) return;

  const customCount = getCustomCount();
  badge.textContent = `${customCount} / ${MAX_CUSTOM_PERSONALITIES} personnalités`;
}

function buildCard(p) {
  const card = document.createElement("div");
  const isStandard = Number(p.id) === 0;

  card.className = "card";
  card.dataset.id = String(p.id);

  card.innerHTML = `
    <div class="card-avatar">${escHtml((p.name || "?").charAt(0).toUpperCase())}</div>
    <div class="card-name">${escHtml(p.name || "")}</div>
    <div class="card-prompt">${escHtml(p.system_prompt || "")}</div>
    <div class="card-actions">
      <button class="btn-edit">✏️ Modifier</button>
      ${
        isStandard
          ? ""
          : `<button class="btn-delete" title="Supprimer">🗑</button>`
      }
    </div>
  `;

  card
    .querySelector(".btn-edit")
    .addEventListener("click", () => openModal(Number(p.id)));

  if (!isStandard) {
    const deleteBtn = card.querySelector(".btn-delete");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", () =>
        deletePersonality(Number(p.id), card),
      );
    }
  }

  return card;
}

function buildAddCard() {
  const maxReached = getCustomCount() >= MAX_CUSTOM_PERSONALITIES;

  const card = document.createElement("div");
  card.className = "card-add" + (maxReached ? " disabled" : "");

  card.innerHTML = `
    <div class="add-plus">＋</div>
    <div class="add-label">Nouvelle personnalité</div>
    ${
      maxReached
        ? `<div class="add-max-hint">Maximum ${MAX_CUSTOM_PERSONALITIES} atteint</div>`
        : ""
    }
  `;

  if (!maxReached) {
    card.addEventListener("click", () => openModal(null));
  }

  return card;
}

function openModal(id) {
  editingId = id;

  const titleEl = document.getElementById("modalTitle");
  const nameInput = document.getElementById("modalName");
  const promptArea = document.getElementById("modalPrompt");

  if (id !== null) {
    const p = personalities.find((x) => Number(x.id) === Number(id));
    if (!p) {
      showToast("Personnalité introuvable", "error");
      return;
    }

    titleEl.textContent = "Modifier la personnalité";
    nameInput.value = p.name || "";
    promptArea.value = p.system_prompt || "";
  } else {
    titleEl.textContent = "Nouvelle personnalité";
    nameInput.value = "";
    promptArea.value = "";
  }

  nameInput.classList.remove("error");
  promptArea.classList.remove("error");

  updateCharCount();
  document.getElementById("modalOverlay").classList.add("open");
  nameInput.focus();
}

function closeModal() {
  document.getElementById("modalOverlay").classList.remove("open");
  editingId = null;
}

function openPersonalityConfirmModal() {
  const overlay = document.getElementById("personalityConfirmOverlay");
  if (!overlay) return;

  const titleEl = document.getElementById("personalityConfirmTitle");
  const nameEl = document.getElementById("personalityConfirmName");
  const proceedBtn = document.getElementById("personalityConfirmProceed");
  const name = pendingPersonalityPayload?.name || "";

  if (titleEl) {
    titleEl.textContent =
      pendingPersonalityId === null
        ? "Créer la personnalité"
        : "Mettre à jour la personnalité";
  }

  if (nameEl) {
    nameEl.textContent = name ? `Nom : ${name}` : "";
  }

  if (proceedBtn) {
    proceedBtn.textContent =
      pendingPersonalityId === null ? "Créer" : "Enregistrer";
    proceedBtn.focus();
  }

  overlay.classList.add("open");
}

function closePersonalityConfirmModal() {
  const overlay = document.getElementById("personalityConfirmOverlay");
  if (!overlay) return;
  overlay.classList.remove("open");
}

function resetPendingPersonality() {
  pendingPersonalityPayload = null;
  pendingPersonalityId = null;
}

function handlePersonalityConfirmProceed() {
  if (!pendingPersonalityPayload) {
    closePersonalityConfirmModal();
    return;
  }

  const payload = pendingPersonalityPayload;
  const targetId = pendingPersonalityId;
  closePersonalityConfirmModal();
  resetPendingPersonality();
  performModalSave(payload, targetId);
}

function openUploadConfirmModal() {
  const overlay = document.getElementById("uploadConfirmOverlay");
  if (!overlay) return;
  overlay.classList.add("open");

  const proceedBtn = document.getElementById("uploadConfirmProceed");
  if (proceedBtn) proceedBtn.focus();
}

function closeUploadConfirmModal() {
  const overlay = document.getElementById("uploadConfirmOverlay");
  if (!overlay) return;
  overlay.classList.remove("open");
}

function handleUploadConfirmProceed() {
  closeUploadConfirmModal();
  const fileInput = document.getElementById("adminFileUpload");
  if (fileInput) fileInput.click();
}

function updateCharCount() {
  const len = document.getElementById("modalPrompt").value.length;
  document.getElementById("charCount").textContent = `${len} / 500`;
}

async function handleModalSave() {
  const nameInput = document.getElementById("modalName");
  const promptArea = document.getElementById("modalPrompt");

  const name = nameInput.value.trim();
  const system_prompt = promptArea.value.trim();

  nameInput.classList.remove("error");
  promptArea.classList.remove("error");

  let valid = true;

  if (!name) {
    nameInput.classList.add("error");
    nameInput.focus();
    valid = false;
  }

  if (!system_prompt) {
    promptArea.classList.add("error");
    if (valid) promptArea.focus();
    valid = false;
  }

  if (!valid) return;

  pendingPersonalityPayload = { name, system_prompt };
  pendingPersonalityId = editingId;
  openPersonalityConfirmModal();
}

async function performModalSave(payload, targetId) {
  const result =
    targetId === null
      ? await apiRequest(API_ENDPOINTS.adminPersonalities, {
          method: "POST",
          body: JSON.stringify(payload),
        })
      : await apiRequest(`${API_ENDPOINTS.adminPersonalities}/${targetId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });

  const { response, data } = result;

  if (!response.ok) {
    console.error("Save personality failed:", data);
    showToast(
      (data && data.detail) || "Erreur lors de l'enregistrement",
      "error",
    );
    return;
  }

  await loadPersonalities();
  renderAll();
  closeModal();
  notifyPersonalitiesChanged();

  showToast(
    targetId === null
      ? `✅ "${payload.name}" ajoutée`
      : `✅ "${payload.name}" modifiée`,
    "success",
  );
}

async function deletePersonality(id, cardEl) {
  const p = personalities.find((x) => Number(x.id) === Number(id));

  if (!p) {
    showToast("Personnalité introuvable", "error");
    return;
  }

  if (Number(id) === 0) {
    showToast("La personnalité Standard ne peut pas être supprimée", "warning");
    return;
  }

  if (!confirm(`Supprimer "${p.name}" ?`)) return;

  cardEl.classList.add("card-removing");

  setTimeout(async () => {
    const { response, data } = await apiRequest(
      `${API_ENDPOINTS.adminPersonalities}/${id}`,
      { method: "DELETE" },
    );

    if (!response.ok) {
      console.error("Delete personality failed:", data);
      cardEl.classList.remove("card-removing");
      showToast(
        (data && data.detail) || "Erreur lors de la suppression",
        "error",
      );
      return;
    }

    await loadPersonalities();
    renderAll();
    notifyPersonalitiesChanged();
    showToast(`🗑 "${p.name}" supprimée`, "warning");
  }, 260);
}

async function fetchAllUsers() {
  const token = localStorage.getItem(LS_TOKEN);

  const url =
    typeof API_ENDPOINTS !== "undefined" && API_ENDPOINTS.listUsers
      ? `${API_ENDPOINTS.listUsers}?token=${encodeURIComponent(token)}`
      : `${API_BASE_URL}/admin/users?token=${encodeURIComponent(token)}`;

  const { response, data } = await apiRequest(url, {
    method: "GET",
  });

  console.log("LIST USERS:", response.status, data);

  if (!response.ok) {
    const msg =
      typeof data?.detail === "string"
        ? data.detail
        : JSON.stringify(data?.detail || data || "Erreur inconnue");

    showToast(msg, "error");
    return null;
  }

  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.users)) return data.users;

  console.error("Format users inattendu:", data);
  showToast("Format users inattendu.", "error");
  return null;
}

function renderUsers(users) {
  if (!users || users.length === 0) {
    return `<div class="user-row">Aucun utilisateur trouvé.</div>`;
  }

  return `
    <div class="user-row header">
      <div>ID</div>
      <div>Nom complet</div>
      <div>Username</div>
      <div>Admin</div>
    </div>
    ${users
      .map(
        (u) => `
          <div class="user-row">
            <div>${escHtml(u.id ?? "")}</div>
            <div>${escHtml(u.full_name ?? "")}</div>
            <div>${escHtml(u.username ?? "")}</div>
            <div>${u.is_admin ? "Oui" : "Non"}</div>
          </div>
        `,
      )
      .join("")}
  `;
}

function bindEnterToButton(inputIds, buttonId) {
  inputIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const btn = document.getElementById(buttonId);
      if (btn) btn.click();
    });
  });
}

function showSearchUserPanel() {
  setActiveNav("navManageUsers");
  setAdminBackAction(showUserManagementHub);
  setAdminLastView("manage_users:search");

  openAdminActionPanel(
    "Chercher User",
    `
      <div class="admin-form">
        <label>Username</label>
        <input id="searchUsernameInput" type="text" placeholder="Ex: Adel" autocomplete="off" />
        <div class="admin-form-actions">
          <button class="btn-save" id="searchUsernameBtn">Chercher</button>
        </div>
      </div>
    `,
  );

  document
    .getElementById("searchUsernameBtn")
    .addEventListener("click", handleSearchUser);

  bindEnterToButton(["searchUsernameInput"], "searchUsernameBtn");
}

async function handleSearchUser() {
  const input = document.getElementById("searchUsernameInput");
  const result = document.getElementById("adminActionResult");
  const username = input.value.trim();

  if (!username) {
    input.focus();
    showToast("Entre un username.", "warning");
    return;
  }

  result.innerHTML = `<div class="user-row">Recherche...</div>`;

  const users = await fetchAllUsers();
  if (!users) {
    result.innerHTML = `<div class="user-row">Erreur de chargement.</div>`;
    return;
  }

  const found = users.filter(
    (u) => String(u.username || "").toLowerCase() === username.toLowerCase(),
  );

  result.innerHTML = renderUsers(found);

  if (found.length === 0) {
    showToast("Utilisateur introuvable.", "warning");
  } else {
    showToast("Utilisateur trouvé.", "success");
  }
}

async function handleListUsers() {
  setActiveNav("navManageUsers");
  setAdminBackAction(showUserManagementHub);
  setAdminLastView("manage_users:list");

  openAdminActionPanel("List All Users", "");

  const result = document.getElementById("adminActionResult");
  result.innerHTML = `<div class="user-row">Chargement...</div>`;

  const users = await fetchAllUsers();

  if (!users) {
    result.innerHTML = `<div class="user-row">Erreur de chargement.</div>`;
    return;
  }

  result.innerHTML = renderUsers(users);
  showToast("Liste des utilisateurs chargée.", "success");
}

function showUpdateAdminPanel() {
  setActiveNav("navManageUsers");
  setAdminBackAction(showUserManagementHub);
  setAdminLastView("manage_users:promote");

  openAdminActionPanel(
    "Update User to Admin",
    `
      <div class="admin-form">
        <label>Username</label>
        <input id="updateAdminUsername" type="text" placeholder="Ex: Souad" autocomplete="off" />

        <label>Mot de passe</label>
        <input id="updateAdminSecret" type="password" placeholder="Mot de passe admin" autocomplete="off" />

        <label>Statut admin</label>
        <select id="updateAdminStatus">
          <option value="true">Mettre Admin</option>
        </select>

        <div class="admin-form-actions">
          <button class="btn-save" id="updateAdminBtn">Mettre à jour</button>
        </div>
      </div>
    `,
  );

  document
    .getElementById("updateAdminBtn")
    .addEventListener("click", handleUpdateAdmin);

  bindEnterToButton(
    ["updateAdminUsername", "updateAdminSecret", "updateAdminStatus"],
    "updateAdminBtn",
  );
}

async function handleUpdateAdmin() {
  const usernameInput = document.getElementById("updateAdminUsername");
  const statusInput = document.getElementById("updateAdminStatus");
  const secretInput = document.getElementById("updateAdminSecret");

  const target_username = usernameInput.value.trim();
  const is_admin = true;
  const admin_secret = secretInput ? secretInput.value.trim() : "";

  if (!target_username) {
    usernameInput.focus();
    showToast("Entre un username.", "warning");
    return;
  }

  const token = localStorage.getItem(LS_TOKEN);

  const payload = {
    token,
    target_username,
    is_admin,
  };

  if (admin_secret) {
    payload.admin_secret = admin_secret;
  }

  const { response, data } = await apiRequest(API_ENDPOINTS.updateUserAdmin, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    showToast(
      (data && data.detail) || "Erreur lors de la mise à jour.",
      "error",
    );
    return;
  }

  showToast("Utilisateur mis admin.", "success");
  await handleListUsers();
}

function showUpdateUsernamePanel() {
  setActiveNav("navManageUsers");
  setAdminBackAction(showUserManagementHub);
  setAdminLastView("manage_users:rename");

  openAdminActionPanel(
    "Modifier Username",
    `
      <div class="admin-form">
        <label>Username actuel</label>
        <input id="currentUsername" type="text" placeholder="Ex: Sarah" autocomplete="off" />

        <label>Nouveau username</label>
        <input id="newUsername" type="text" placeholder="Ex: Asma" autocomplete="off" />

        <div class="admin-form-actions">
          <button class="btn-save" id="updateUsernameBtn">Modifier</button>
        </div>
      </div>
    `,
  );

  document
    .getElementById("updateUsernameBtn")
    .addEventListener("click", handleUsernameUpdate);

  bindEnterToButton(["currentUsername", "newUsername"], "updateUsernameBtn");
}

async function handleUsernameUpdate() {
  const currentInput = document.getElementById("currentUsername");
  const newInput = document.getElementById("newUsername");

  const currentUsername = currentInput.value.trim();
  const newUsername = newInput.value.trim();

  if (!currentUsername) {
    currentInput.focus();
    showToast("Entre le username actuel.", "warning");
    return;
  }

  if (!newUsername) {
    newInput.focus();
    showToast("Entre le nouveau username.", "warning");
    return;
  }

  if (currentUsername === newUsername) {
    showToast("Le nouveau username doit être différent.", "warning");
    return;
  }

  const token = localStorage.getItem(LS_TOKEN);

  const { response, data } = await apiRequest(API_ENDPOINTS.updateUsername, {
    method: "POST",
    body: JSON.stringify({
      token,
      target_username: currentUsername,
      new_username: newUsername,
    }),
  });

  if (!response.ok) {
    showToast(
      (data && data.detail) || "Erreur lors de la mise à jour.",
      "error",
    );
    return;
  }

  const storedUsername = (localStorage.getItem(LS_USER) || "").trim();
  if (storedUsername === currentUsername) {
    localStorage.setItem(LS_USER, newUsername);
    initUserCard();
  }

  showToast("Username modifié.", "success");
  await handleListUsers();
}

function showDeleteUserPanel() {
  setActiveNav("navManageUsers");
  setAdminBackAction(showUserManagementHub);
  setAdminLastView("manage_users:delete");

  openAdminActionPanel(
    "Delete User",
    `
      <div class="admin-form">
        <label>Username à supprimer</label>
        <input id="deleteUsername" type="text" placeholder="Ex: Feriel" autocomplete="off" />

        <div class="admin-form-actions">
          <button class="btn-save" id="deleteUserBtn">Supprimer</button>
        </div>
      </div>
    `,
  );

  document
    .getElementById("deleteUserBtn")
    .addEventListener("click", handleDeleteUser);

  bindEnterToButton(["deleteUsername"], "deleteUserBtn");
}

async function handleDeleteUser() {
  const input = document.getElementById("deleteUsername");
  const target_username = input.value.trim();

  if (!target_username) {
    input.focus();
    showToast("Entre un username.", "warning");
    return;
  }

  if (!confirm(`Supprimer l'utilisateur "${target_username}" ?`)) return;

  const token = localStorage.getItem(LS_TOKEN);
  const deleteUrl =
    API_ENDPOINTS.deleteUser || `${API_BASE_URL}/admin/delete-user`;

  const { response, data } = await apiRequest(deleteUrl, {
    method: "POST",
    body: JSON.stringify({
      token,
      target_username,
    }),
  });

  if (!response.ok) {
    showToast(
      (data && data.detail) || "Erreur lors de la suppression.",
      "error",
    );
    return;
  }

  showToast("Utilisateur supprimé.", "success");
  await handleListUsers();
}

function showRegisterUserPanel() {
  setActiveNav("navManageUsers");
  setAdminBackAction(showUserManagementHub);
  setAdminLastView("manage_users:register");

  openAdminActionPanel(
    "Register New User",
    `
      <div class="admin-form">
        <label>Full name</label>
        <input id="registerFullName" type="text" placeholder="Ex: Feriel Aitou" autocomplete="off" />

        <label>Username</label>
        <input id="registerUsername" type="text" placeholder="Ex: feriel" autocomplete="off" />

        <label>Créer comme admin ?</label>
        <select id="registerIsAdmin">
          <option value="false">Non</option>
          <option value="true">Oui</option>
        </select>

        <label>Mot de passe si admin</label>
        <input id="registerAdminSecret" type="password" placeholder="Optionnel sauf admin" autocomplete="off" />

        <div class="admin-form-actions">
          <button class="btn-save" id="registerUserBtn">Créer</button>
        </div>
      </div>
    `,
  );

  document
    .getElementById("registerUserBtn")
    .addEventListener("click", handleRegisterUser);

  bindEnterToButton(
    [
      "registerFullName",
      "registerUsername",
      "registerIsAdmin",
      "registerAdminSecret",
    ],
    "registerUserBtn",
  );
}

async function handleRegisterUser() {
  const fullNameInput = document.getElementById("registerFullName");
  const usernameInput = document.getElementById("registerUsername");
  const isAdminInput = document.getElementById("registerIsAdmin");
  const secretInput = document.getElementById("registerAdminSecret");
  const result = document.getElementById("adminActionResult");

  const full_name = fullNameInput.value.trim();
  const username = usernameInput.value.trim();
  const is_admin = isAdminInput.value === "true";
  const admin_secret = secretInput.value.trim();

  if (!full_name) {
    fullNameInput.focus();
    showToast("Entre le full name.", "warning");
    return;
  }

  if (!username) {
    usernameInput.focus();
    showToast("Entre le username.", "warning");
    return;
  }

  const body = {
    full_name,
    username,
    is_admin,
  };

  if (admin_secret) {
    body.admin_secret = admin_secret;
  }

  const { response, data } = await apiRequest(API_ENDPOINTS.register, {
    method: "POST",
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    showToast((data && data.detail) || "Erreur lors de la création.", "error");
    return;
  }

  result.innerHTML = `
    <div class="user-row">
      <div>✅</div>
      <div>Utilisateur créé</div>
      <div>${escHtml(username)}</div>
      <div>${is_admin ? "Admin" : "User"}</div>
    </div>
    ${
      data && data.password
        ? `<div class="user-row"><div>🔑</div><div>Mot de passe</div><div>${escHtml(data.password)}</div><div>À copier</div></div>`
        : ""
    }
  `;

  showToast("Utilisateur créé.", "success");
}

async function handleAdminFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  showToast(`Upload de ${file.name} en cours...`, "warning");

  const { response, data } = await apiRequest(API_ENDPOINTS.upload, {
    method: "POST",
    body: formData,
  });

  e.target.value = "";

  if (!response.ok) {
    showToast((data && data.detail) || "Erreur upload file.", "error");
    return;
  }

  showToast("Fichier uploadé avec succès.", "success");
}

let toastTimer = null;

function showToast(msg, type = "success") {
  const t = document.getElementById("toast");
  if (!t) return;

  clearTimeout(toastTimer);

  if (typeof msg === "object") {
    msg = JSON.stringify(msg);
  }

  t.textContent = String(msg);
  t.className = `toast ${type} show`;

  toastTimer = setTimeout(() => {
    t.classList.remove("show");
  }, 2800);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
