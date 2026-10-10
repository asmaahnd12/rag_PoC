# Frontend Documentation

Vanilla JavaScript frontend for PFE-RAG system with responsive dark UI and role-based pages.

## 📁 Structure

```
front-end/
├── config.js          # API base URL & shared config
├── lib/               # Third-party libraries
│   └── marked.min.js  # Markdown parser for chat
├── login/             # Authentication page
├── chat/              # Main chat interface
├── admin/             # Admin dashboard
├── stats/             # Statistics page
└── assets/            # Images & logos
```

## 🎨 Key Pages

| Page      | Path            | Purpose                                   | Access         |
| --------- | --------------- | ----------------------------------------- | -------------- |
| **Login** | `/` or `/login` | User authentication with JWT              | Public         |
| **Chat**  | `/chat`         | Multi-turn conversations with RAG support | Users + Admins |
| **Admin** | `/admin`        | Manage users, documents, vector store     | Admins only    |
| **Stats** | `/stats`        | View system statistics & metrics          | Admins only    |

## 🔄 API Integration

All pages communicate with the backend at configured `API_BASE_URL` in `config.js`.

**Key endpoints used:**

- `POST /auth/login` - User authentication
- `POST /chat/new` - Create chat session
- `POST /chat/message` - Send message with RAG
- `GET /admin/users` - User management
- `GET /admin/stats` - System statistics

## 🛠️ Technologies

- **Vanilla JavaScript** - No framework dependencies
- **CSS3** - Dark theme with glassmorphism effects
- **Marked.js** - Markdown rendering in chat responses
- **REST API** - FastAPI backend integration

## 🚀 Development

No build step required - serve files directly with any HTTP server.

```bash
# Simple Python server
python3 -m http.server 8000

# Or use Node.js
npx http-server
```

Then visit `http://localhost:8000/static/login/login.html`

## 📝 Configuration

Update `config.js` to set your backend URL:

```javascript
const API_BASE_URL = "http://your-backend:8000";
```
