# WRO Budget Manager

A complete, production-ready, dark-themed Flask web application to manage, track, and analyze team expenditures and allocations.

## Features
- **Role-Based Access Control (RBAC)**: Distinct views and controls for Admin and Teammate roles.
- **Interactive Visualizations**: Features dual Chart.js graphs mapping allocated vs actual budgets, and cumulative expenditure burn rates. All visual reporting utilizes Rupee (₹) and Indian currency formats.
- **Dynamic Transaction Logger**: Log single purchases with an arbitrary number of component line-items added on-the-fly using JavaScript.
- **Secured Invoicing**: Restricted, secure PDF-only upload handler for storing receipts.
- **Transaction Manager**: Interactive expandable list of transactions displaying nested component details and direct PDF downloads.
- **CSV Data Exporter**: Downloadable CSV detailing every logged purchase and component item for financial audits.
- **Pre-Seeded Database**: Auto-seeds default admin and teammate profiles on startup using environment variables.
- **Password Toggle**: Password visibility toggle ("Show/Hide") on the login interface.

---

## Technical Stack
- **Backend**: Python 3.x, Flask
- **Database**: Relational SQLite via Flask-SQLAlchemy
- **Security**: Flask-WTF (global CSRF Protection), Werkzeug (secure password hashing)
- **Frontend**: Tailwind CSS CDN, Chart.js CDN, Vanilla JavaScript (DOM manipulation)

---

## Installation & Setup

1. **Install Dependencies**:
   Ensure you have Python installed, then run:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**:
   Create a file named `.env` in the root directory and configure usernames and passwords:
   ```env
   # Flask configurations
   SECRET_KEY=wro-budget-manager-super-secret-key-12345

   # Seeded credentials configuration
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=adminpassword123

   MANTHAN_USERNAME=manthan
   MANTHAN_PASSWORD=manthanpassword123

   DINESH_USERNAME=dinesh
   DINESH_PASSWORD=dineshpassword123
   ```

3. **Run the Application**:
   Startup the local development server:
   ```bash
   python app.py
   ```
   The application will start on `http://127.0.0.1:5000/`.

4. **Database Pre-Seeding**:
   The application automatically initializes a relational SQLite database file `wro_budget.db` and seeds it with default users from the `.env` configuration if they do not exist.

---

## Code Structure

- [app.py](file:///D:/Python/Personal/Web%20Dev/WRO_Budget%20Manager/app.py) - Main application configuration, models, database seeding, RBAC handlers, and routes.
- [templates/login.html](file:///D:/Python/Personal/Web%20Dev/WRO_Budget%20Manager/templates/login.html) - Premium login page with password toggle and dark glassmorphic styling.
- [templates/dashboard.html](file:///D:/Python/Personal/Web%20Dev/WRO_Budget%20Manager/templates/dashboard.html) - Core interface containing metric cards, Chart.js templates, transaction list, and modals.
- [templates/edit_buy.html](file:///D:/Python/Personal/Web%20Dev/WRO_Budget%20Manager/templates/edit_buy.html) - Admin-only transaction editor.
- `static/uploads/proofs/` - Upload directory for invoice PDFs.
- `requirements.txt` - Python module list.
