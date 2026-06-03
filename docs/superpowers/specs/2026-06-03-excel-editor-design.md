# 多用户 Excel 在线编辑系统 — 设计文档

**日期：** 2026-06-03
**方案：** Flask + PostgreSQL + Handsontable（方案 B）

---

## 1. 概述

管理员上传 Excel 文件到网页，解析后存储到数据库。普通用户登录后进入在线电子表格界面，只能编辑自己被授权的矩形区域（如 C3:D4），其余单元格只读。所有修改记录审计日志，管理员可查看和回滚。

## 2. 功能清单

| # | 功能 | 描述 |
|---|------|------|
| ① | 用户系统 | 自行注册、登录、管理员可为用户设置权限 |
| ② | 表格上传与存储 | 管理员上传 Excel → 解析存库 → 列表页查看已有表格 |
| ③ | 数据展示与编辑 | 点击表格进入详情，Handsontable 呈现，按权限锁定只读区域 |
| ④ | 修改保存与日志 | 用户修改单元格 → 校验权限 → 写入数据 + 审计日志 |
| ⑤ | 权限管理界面 | 管理员可视化为用户分配矩形编辑区域 |

## 3. 数据库表设计（PostgreSQL，共 7 张表）

### 3.1 users — 用户表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 主键 |
| username | VARCHAR(50) UNIQUE NOT NULL | 登录名 |
| email | VARCHAR(120) UNIQUE NOT NULL | 邮箱 |
| password_hash | VARCHAR(256) NOT NULL | bcrypt 哈希 |
| is_admin | BOOLEAN DEFAULT FALSE | 是否管理员 |
| is_active | BOOLEAN DEFAULT TRUE | 账号启用标志 |
| created_at | TIMESTAMP DEFAULT NOW() | 注册时间 |

### 3.2 excel_files — 上传文件

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 主键 |
| display_name | VARCHAR(200) NOT NULL | 展示名称 |
| original_filename | VARCHAR(256) NOT NULL | 原始文件名 |
| stored_path | VARCHAR(512) NOT NULL | 服务器存储路径 |
| uploaded_by | FK → users.id | 上传者 |
| is_active | BOOLEAN DEFAULT TRUE | 软删除标记 |
| created_at | TIMESTAMP DEFAULT NOW() | 上传时间 |

### 3.3 sheets — 工作表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 主键 |
| file_id | FK → excel_files.id NOT NULL | 所属文件 |
| sheet_name | VARCHAR(100) NOT NULL | Sheet 名称 |
| sheet_order | INT NOT NULL | 排序序号 |
| created_at | TIMESTAMP DEFAULT NOW() | 创建时间 |

### 3.4 sheet_columns — 列定义

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 主键 |
| sheet_id | FK → sheets.id NOT NULL | 所属工作表 |
| column_key | VARCHAR(100) NOT NULL | 列标识（标准化列头） |
| column_label | VARCHAR(200) NOT NULL | 列显示名（原始列头） |
| column_order | INT NOT NULL | 列序号（0-based） |

唯一约束：`UNIQUE(sheet_id, column_order)`

### 3.5 sheet_rows — 行数据

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 主键 |
| sheet_id | FK → sheets.id NOT NULL | 所属工作表 |
| row_order | INT NOT NULL | 行序号（0-based） |
| data | JSONB NOT NULL | 整行数据，格式 `{"列A":"值1","列B":"值2"}` |

唯一约束：`UNIQUE(sheet_id, row_order)`

**设计理由：** JSONB 存储整行，导入导出快、结构灵活。区域权限在应用层校验。

### 3.6 user_range_permissions — 用户区域权限

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 主键 |
| user_id | FK → users.id NOT NULL | 被授权用户 |
| sheet_id | FK → sheets.id NOT NULL | 目标工作表 |
| col_start | INT NOT NULL | 起始列索引（0-based） |
| col_end | INT NOT NULL | 结束列索引（0-based，含） |
| row_start | INT NOT NULL | 起始行索引（0-based） |
| row_end | INT NOT NULL | 结束行索引（0-based，含） |
| granted_by | FK → users.id NOT NULL | 授权人（管理员） |
| created_at | TIMESTAMP DEFAULT NOW() | 授权时间 |

**索引约定：**
- 列索引从 0 开始（A=0, B=1, C=2, ...）
- 行索引从 0 开始，row_order=0 为第一行数据行（表头不占行索引，存储在 sheet_columns 中）
- **示例：** 管理员选中 C3:D4（Excel 坐标，C 列第 3-4 行）→ col_start=2, col_end=3, row_start=2, row_end=3

一个用户可拥有同一 sheet 的多个不连续区域（插入多条记录）。

### 3.7 edit_history — 编辑历史

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 主键 |
| user_id | FK → users.id NOT NULL | 编辑者 |
| sheet_id | FK → sheets.id NOT NULL | 工作表 |
| row_id | FK → sheet_rows.id | 被编辑行 |
| column_key | VARCHAR(100) NOT NULL | 被编辑列 |
| old_value | TEXT | 旧值 |
| new_value | TEXT | 新值 |
| edited_at | TIMESTAMP DEFAULT NOW() | 编辑时间 |

### ER 关系图

```
users 1──N excel_files           (上传)
users 1──N user_range_permissions (被授权)
users 1──N edit_history          (编辑)

excel_files 1──N sheets

sheets 1──N sheet_columns
sheets 1──N sheet_rows
sheets 1──N user_range_permissions

sheet_rows 1──N edit_history
```

## 4. Flask 项目结构

```
pengsheng/
├── app/
│   ├── __init__.py              # create_app() 工厂函数
│   ├── config.py                # Dev / Prod / Test 配置类
│   ├── extensions.py            # db, login_manager, migrate 实例
│   ├── models.py                # 7 张表 ORM 模型
│   │
│   ├── auth/                    # 认证蓝图
│   │   ├── __init__.py          # Blueprint('auth', __name__)
│   │   ├── forms.py             # LoginForm, RegisterForm (WTForms)
│   │   └── routes.py            # /login, /register, /logout
│   │
│   ├── admin/                   # 管理员蓝图 (/admin)
│   │   ├── __init__.py
│   │   ├── forms.py             # UploadForm, PermissionForm
│   │   └── routes.py            # 上传、列表、权限分配、导出、历史
│   │
│   ├── editor/                  # 编辑蓝图 (/editor, /api)
│   │   ├── __init__.py
│   │   └── routes.py            # 表格数据接口、保存接口
│   │
│   ├── templates/
│   │   ├── base.html            # 基础布局
│   │   ├── auth/
│   │   │   ├── login.html
│   │   │   └── register.html
│   │   ├── admin/
│   │   │   ├── dashboard.html   # 文件列表
│   │   │   ├── upload.html      # 上传页
│   │   │   └── permissions.html # 权限分配页
│   │   └── editor/
│   │       ├── file_list.html   # 用户文件列表
│   │       └── editor.html      # Handsontable 编辑器
│   │
│   └── static/
│       ├── css/style.css
│       └── js/editor.js         # 前端表格渲染与交互
│
├── utils/
│   ├── __init__.py
│   ├── excel_io.py              # openpyxl 导入/导出
│   └── decorators.py            # @admin_required
│
├── migrations/                  # Flask-Migrate 生成
├── uploads/                     # 上传 Excel 存放
├── .env
├── requirements.txt
└── run.py                       # 入口
```

## 5. 路由设计

| 路由 | 方法 | 蓝图 | 功能 |
|------|------|------|------|
| `/auth/login` | GET/POST | auth | 登录 |
| `/auth/register` | GET/POST | auth | 注册 |
| `/auth/logout` | GET | auth | 登出 |
| `/` | GET | editor | 用户首页（可编辑文件列表） |
| `/editor/<file_id>/<sheet_id>` | GET | editor | 编辑器页面 |
| `/api/sheet/<sheet_id>/data` | GET | editor | 返回 JSON：表格数据 + 当前用户权限区域 |
| `/api/sheet/<sheet_id>/save` | POST | editor | 保存单元格变更 |
| `/admin/` | GET | admin | 管理员控制台（文件列表） |
| `/admin/upload` | GET/POST | admin | 上传 Excel |
| `/admin/users` | GET | admin | 用户列表（选择为谁分配权限） |
| `/admin/permissions/<user_id>/<file_id>` | GET/POST | admin | 为用户分配矩形编辑区域 |
| `/admin/history/<file_id>` | GET | admin | 查看编辑历史 |
| `/api/file/<file_id>/export` | GET | admin | 导出为 Excel |

## 6. 权限校验流程

```
用户 POST /api/sheet/<id>/save
  → 后端遍历每个被修改的单元格 (row, col)
  → 查询 user_range_permissions WHERE user_id=current_user AND sheet_id=<id>
  → 判断是否存在任意一条记录满足:
      col_start <= col <= col_end AND row_start <= row <= row_end
  → 所有修改都通过 → 写入 sheet_rows.data (JSONB) + edit_history
  → 存在越权修改 → 拒绝全部，返回 403
```

## 7. 前端 Handsontable 集成

- `GET /api/sheet/<id>/data` 返回：
  ```json
  {
    "columns": ["姓名", "年龄", "工资", "部门"],
    "rows": [{"姓名":"张三","年龄":"28","工资":"8000","部门":"研发"}, ...],
    "permissions": [
      {"col_start": 2, "col_end": 2, "row_start": 0, "row_end": 9}
    ]
  }
  ```
- `editor.js` 根据 `permissions` 数组，遍历所有单元格：
  - 在权限区域内 → `readOnly: false`
  - 不在任何区域内 → `readOnly: true`，添加灰色背景
- 用户编辑后 AJAX POST `/api/sheet/<id>/save`，body：
  ```json
  {
    "changes": [
      {"row": 3, "col": 2, "old_value": "7500", "new_value": "8000"}
    ]
  }
  ```

## 8. 关键依赖

```
Flask==3.1
Flask-SQLAlchemy==3.1
Flask-Login==0.6
Flask-Migrate==4.1
Flask-WTF==1.2
openpyxl==3.1
psycopg2-binary==2.9
email-validator==2.2
python-dotenv==1.0
```

## 9. 核心模块职责

| 模块 | 职责 |
|------|------|
| `app/models.py` | 7 张表 ORM：User, ExcelFile, Sheet, SheetColumn, SheetRow, UserRangePermission, EditHistory |
| `utils/excel_io.py` | `import_excel(filepath)` 读取 Excel → 写入 sheets/sheet_columns/sheet_rows；`export_excel(file_id)` 从库重建 Excel |
| `admin/routes.py` | 管理员专属：文件 CRUD、用户列表、权限分配、编辑历史查看 |
| `editor/routes.py` | 核心编辑：返回表格数据+权限、校验并保存修改、写审计日志 |
| `static/js/editor.js` | Handsontable 初始化、权限区域锁定、单元格变更事件、AJAX 提交 |
