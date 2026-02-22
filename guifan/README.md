# AI Agent 自动化开发脚手架

基于 Anthropic 长期运行 Agent 最佳实践的简化版本。

## 核心文件（5个）

1. **CLAUDE.md** - AI工作流程指南（提示词）
2. **task.json** - 任务列表
3. **progress.txt** - 工作日志
4. **init.bat** - 环境初始化脚本
5. **项目文件** - 你的实际项目代码（如index.html, server.js等）

## 快速开始

### 1. 初始化项目

```bash
# 运行初始化脚本
init.bat

# 或手动启动
npm install
node server.js
```

### 2. 配置任务列表

编辑 [task.json](task.json)，添加你的任务：

```json
[
  {
    "id": "task-001",
    "description": "实现用户登录功能",
    "steps": [
      "创建登录表单",
      "实现验证逻辑",
      "测试登录流程"
    ],
    "passes": false
  }
]
```

### 3. 让AI开始工作

在Claude Code中，将 [CLAUDE.md](CLAUDE.md) 的内容作为系统提示词，AI会自动：

1. 读取task.json找到未完成任务
2. 实现功能
3. 运行测试（npm run lint, npm run build, 浏览器测试）
4. 更新progress.txt
5. 更新task.json（标记完成）
6. 提交git commit

## 工作流程

```
┌─────────────────┐
│  1. 运行init.bat │
│  启动开发环境    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. 读取task.json│
│ 选择passes:false │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. 实现功能     │
│  编写代码        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. 测试验证     │
│  lint/build/浏览器│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. 更新文件      │
│ progress.txt     │
│ task.json        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 6. 提交代码      │
│ git commit       │
└─────────────────┘
```

## 核心原则

### 1. 增量工作
- 一次只完成一个任务
- 不要试图一次性完成所有功能

### 2. 彻底测试
- 必须使用浏览器自动化测试
- 不能只依赖代码检查
- 需要截图验证

### 3. 清洁状态
- 每次会话结束时代码可合并
- 没有重大bug
- 所有修改已提交

### 4. 详细记录
- progress.txt记录所有工作
- 供下一个会话参考

## task.json 格式

```json
[
  {
    "id": "task-001",           // 任务ID
    "description": "任务描述",   // 简短描述
    "steps": [                  // 测试步骤
      "步骤1",
      "步骤2",
      "步骤3"
    ],
    "passes": false             // 是否完成（只能改这个字段！）
  }
]
```

**重要规则**:
- ✅ 只能修改 `passes` 字段
- ❌ 不能删除任务
- ❌ 不能修改描述或步骤
- ❌ 不能重新排序

## progress.txt 格式

```markdown
### 会话 X - YYYY-MM-DD HH:MM
**完成任务**: task-XXX - [任务描述]

**实现内容**:
- [具体做了什么]

**测试结果**:
- [测试通过的内容]

**遇到的问题**:
- [问题描述]

**解决方案**:
- [如何解决]

**下一步计划**: task-YYY

**进度**: X/总数 任务完成

---
```

## 测试要求

### 必须使用浏览器自动化

使用Chrome DevTools MCP工具：

```javascript
// 导航
mcp__chrome-devtools__navigate_page({url: "http://localhost:3000"})

// 截图
mcp__chrome-devtools__take_screenshot()

// 点击
mcp__chrome-devtools__click({uid: "element_uid"})

// 填写
mcp__chrome-devtools__fill({uid: "input_uid", value: "test"})
```

### 测试清单

- ✅ 通过真实浏览器测试
- ✅ 截图验证视觉效果
- ✅ 检查控制台错误
- ✅ 验证完整用户流程
- ❌ 不要只用curl测试
- ❌ 不要跳过视觉验证

## 遇到困难时

AI会在以下情况向你求助：

1. **技术问题**: 无法理解需求、不确定方案、无法解决bug
2. **环境问题**: 服务器无法启动、依赖安装失败
3. **流程问题**: 格式不清楚、不确定是否继续

## 项目结构

```
your-project/
├── CLAUDE.md          # AI工作指南（提示词）
├── task.json          # 任务列表
├── progress.txt       # 工作日志
├── init.bat           # 初始化脚本
├── init.sh            # Linux/Mac初始化脚本
├── package.json       # 项目依赖
├── server.js          # 开发服务器
├── index.html         # 项目文件
└── .git/              # Git仓库
```

## 使用示例

### 场景1: 新项目

```bash
# 1. 创建项目目录
mkdir my-project
cd my-project

# 2. 复制脚手架文件
copy CLAUDE.md task.json progress.txt init.bat

# 3. 编辑task.json添加你的任务

# 4. 初始化git
git init
git add .
git commit -m "Initial commit"

# 5. 在Claude Code中使用CLAUDE.md作为提示词
```

### 场景2: 现有项目

```bash
# 1. 进入项目目录
cd existing-project

# 2. 添加脚手架文件
copy CLAUDE.md task.json progress.txt init.bat

# 3. 根据项目修改init.bat

# 4. 创建task.json列出待办任务

# 5. 提交
git add CLAUDE.md task.json progress.txt init.bat
git commit -m "Add AI agent scaffold"
```

## 最佳实践

### 1. 任务粒度

**好的任务**:
```json
{
  "id": "task-001",
  "description": "实现用户登录表单UI",
  "steps": ["创建表单", "添加样式", "测试响应式"]
}
```

**不好的任务**:
```json
{
  "id": "task-001",
  "description": "完成整个用户系统",  // 太大！
  "steps": ["做完所有功能"]
}
```

### 2. 测试步骤要具体

**好的步骤**:
```json
"steps": [
  "打开 http://localhost:3000",
  "点击'登录'按钮",
  "输入用户名: test@example.com",
  "输入密码: password123",
  "点击'提交'",
  "验证跳转到首页"
]
```

**不好的步骤**:
```json
"steps": [
  "测试登录"  // 太模糊！
]
```

### 3. 保持进度日志详细

每次会话都要记录：
- 做了什么
- 遇到什么问题
- 如何解决
- 下一步计划

## 参考资料

- [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [GitHub: autonomous-coding quickstart](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding)

## License

MIT
