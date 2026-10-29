import sqlite3

conn = sqlite3.connect('nexora.db')
cursor = conn.cursor()

# Create workspaces table
cursor.execute("""
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    repository_url VARCHAR(500),
    repository_type VARCHAR(50) DEFAULT 'python',
    initial_commit_hash VARCHAR(64),
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")

# Insert sample workspaces
cursor.execute("""
INSERT OR IGNORE INTO workspaces (id, name, description, repository_url, repository_type, initial_commit_hash) VALUES
('a56d2ead-69dd-4116-9842-014a16180562', 'sample-calculator', 'Simple calculator with a failing empty-input test', 'https://github.com/nexora-fixtures/sample-calculator', 'python', 'abc123def456'),
('080779e3-92d9-411b-b9ab-f627b1e07c2e', 'sample-api', 'Minimal FastAPI service with a bug in request validation', 'https://github.com/nexora-fixtures/sample-api', 'python', 'def456ghi789'),
('1636fe8f-3616-4b89-8107-3d491fa7d2ab', 'sample-cli', 'CLI tool with argument parsing issue', 'https://github.com/nexora-fixtures/sample-cli', 'python', 'ghi789jkl012')
""")

conn.commit()

# Verify
cursor.execute('SELECT * FROM workspaces')
rows = cursor.fetchall()
for row in rows:
    print(row)

conn.close()
print("Workspaces table created and populated!")