# Interview prep & LinkedIn copy

## 30-second pitch
"FreelanceHub is a freelancer marketplace I built for my DBMS course using Flask and SQLite. The focus was database design: a normalised 5+ table schema with foreign keys, constraints, indexes and a view, plus an atomic hiring transaction so two concurrent requests can never hire two people. I also added live updates, where a client sees new bids appear without refreshing."

## Questions you should be ready for
1. **Why a separate `hiring` table when `bids.status` exists?** It is the contract record (hired/completed dates, lifecycle status), and `UNIQUE(project_id)` makes "one hire per project" a database guarantee. Bids are proposals; hiring is the agreement.
2. **Which normal form?** Skills were comma-separated (violates 1NF), so I moved them to `skills` + `freelancer_skills` (many-to-many). Other tables have no partial or transitive dependencies, so 3NF.
3. **Two clients click Hire at once?** `UPDATE projects SET status='Hired' WHERE status='Open'` inside `BEGIN IMMEDIATE`, checking `rowcount`. Only the first succeeds. `UNIQUE(project_id)` on `hiring` is the second safety net.
4. **What is the view for?** `v_project_summary` aggregates bid count and lowest bid so the dashboard query stays simple.
5. **How is it real-time?** Short polling every 3 s, not WebSockets. Trade-off: simpler, but more requests. Next step is SSE or Flask-SocketIO.
6. **ON DELETE policy?** Child rows cascade when a project is deleted; users with projects or bids are protected by RESTRICT.
7. **Why SQLite?** Zero setup for a demo; weak concurrent writes, so PostgreSQL for production.
8. **How are passwords stored?** Salted hashes via Werkzeug (scrypt), never plaintext.

## LinkedIn post
I built **FreelanceHub**, a freelancer marketplace, for my DBMS course.

Clients post projects, freelancers bid, and the client hires one. New bids and hiring results show up live, with no page refresh.

What I focused on:
• A normalised relational schema (FKs, CHECK/UNIQUE constraints, indexes, a view)
• An atomic hiring transaction that prevents double-hiring
• Hashed passwords, CSRF protection and automated tests

Stack: Python, Flask, SQLite, JavaScript.
Biggest lesson: a test caught a CSRF bypass I had written myself. Testing security assumptions matters.

GitHub: [link]  #Python #Flask #SQL #DBMS #WebDevelopment
