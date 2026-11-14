PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users(
  user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN ('Client','Freelancer')),
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 1:1 with users (only freelancers)
CREATE TABLE IF NOT EXISTS freelancer_profile(
  user_id     INTEGER PRIMARY KEY,
  bio         TEXT DEFAULT '',
  experience  INTEGER NOT NULL DEFAULT 0 CHECK(experience >= 0),
  hourly_rate REAL    NOT NULL DEFAULT 0 CHECK(hourly_rate >= 0),
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Skills normalised (1NF/3NF): many-to-many via junction table
CREATE TABLE IF NOT EXISTS skills(
  skill_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name     TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS freelancer_skills(
  user_id  INTEGER NOT NULL,
  skill_id INTEGER NOT NULL,
  PRIMARY KEY(user_id, skill_id),
  FOREIGN KEY(user_id)  REFERENCES users(user_id)   ON DELETE CASCADE,
  FOREIGN KEY(skill_id) REFERENCES skills(skill_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS projects(
  project_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id   INTEGER NOT NULL,
  title       TEXT NOT NULL,
  description TEXT NOT NULL,
  budget      REAL NOT NULL CHECK(budget > 0),
  deadline    TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Hired','Completed')),
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(client_id) REFERENCES users(user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS bids(
  bid_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    INTEGER NOT NULL,
  freelancer_id INTEGER NOT NULL,
  amount        REAL    NOT NULL CHECK(amount > 0),
  proposal      TEXT    NOT NULL,
  delivery_days INTEGER NOT NULL CHECK(delivery_days > 0),
  status        TEXT    NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Accepted','Rejected')),
  rejection_reason TEXT,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, freelancer_id),              -- one bid per freelancer per project
  FOREIGN KEY(project_id)    REFERENCES projects(project_id) ON DELETE CASCADE,
  FOREIGN KEY(freelancer_id) REFERENCES users(user_id)       ON DELETE RESTRICT
);

-- The contract record. UNIQUE(project_id) => DB itself guarantees one hire per project.
CREATE TABLE IF NOT EXISTS hiring(
  hire_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    INTEGER NOT NULL UNIQUE,
  freelancer_id INTEGER NOT NULL,
  bid_id        INTEGER NOT NULL UNIQUE,
  hired_date    TEXT NOT NULL DEFAULT (datetime('now')),
  completed_date TEXT,
  status        TEXT NOT NULL DEFAULT 'Active' CHECK(status IN ('Active','Completed')),
  FOREIGN KEY(project_id)    REFERENCES projects(project_id) ON DELETE CASCADE,
  FOREIGN KEY(freelancer_id) REFERENCES users(user_id)       ON DELETE RESTRICT,
  FOREIGN KEY(bid_id)        REFERENCES bids(bid_id)         ON DELETE CASCADE
);

-- Powers the real-time notifications
CREATE TABLE IF NOT EXISTS notifications(
  notif_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  message    TEXT NOT NULL,
  link       TEXT,
  is_read    INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bids_project     ON bids(project_id);
CREATE INDEX IF NOT EXISTS idx_bids_freelancer  ON bids(freelancer_id);
CREATE INDEX IF NOT EXISTS idx_projects_status  ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_client  ON projects(client_id);
CREATE INDEX IF NOT EXISTS idx_notif_user       ON notifications(user_id, is_read);

-- View: project + aggregate bid info (used by the client dashboard)
CREATE VIEW IF NOT EXISTS v_project_summary AS
SELECT p.*, COUNT(b.bid_id) AS bid_count, MIN(b.amount) AS lowest_bid
FROM projects p LEFT JOIN bids b ON b.project_id = p.project_id
GROUP BY p.project_id;
