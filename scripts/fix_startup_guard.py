"""Add startup protection guard to prevent state downgrade race condition."""
path = r"C:\Users\mojik\Desktop\mm-auto-3\MathModelAgent-main\frontend\src\stores\task.ts"
with open(path, "r", encoding="utf-8", newline="") as f:
    content = f.read()

# Step 1: Add guard to applyRuntimeState
old_func = "function applyRuntimeState(state: TaskRuntimeState) {\n\t\t\ttaskRuntimeState.value = state;"
new_func = """function applyRuntimeState(state: TaskRuntimeState) {
\t\t\t// 刚启动 5 秒内，不允许把运行态降级为非活跃态
\t\t\t// 防止 WebSocket 连上后 syncTaskSnapshot 读到旧状态覆盖乐观值
\t\t\tconst currentStatus = taskRuntimeState.value?.status;
\t\t\tconst recentlyStarted = Date.now() - lastStartTimestamp < 5000;
\t\t\tif (
\t\t\t\trecentlyStarted &&
\t\t\t\tisActiveStatus(currentStatus) &&
\t\t\t\t!isActiveStatus(state.status)
\t\t\t) {
\t\t\t\treturn;
\t\t\t}
\t\t\ttaskRuntimeState.value = state;"""

if old_func in content:
    content = content.replace(old_func, new_func)
    print("Step 1: Guard added to applyRuntimeState")
else:
    print("Step 1 FAILED")

# Step 2: Add lastStartTimestamp declaration before applyRuntimeState
old_decl = "function applyRuntimeState(state: TaskRuntimeState) {"
new_decl = "let lastStartTimestamp = 0;\n\n\tfunction applyRuntimeState(state: TaskRuntimeState) {"
if old_decl in content:
    content = content.replace(old_decl, new_decl)
    print("Step 2: lastStartTimestamp declared")
else:
    print("Step 2 FAILED")

# Step 3: Set lastStartTimestamp in startTask when we optimistically set running
old_opt = "\t\t\t\t// 先乐观切到运行态，避免 refreshTaskState 读到后端异步任务\n\t\t\t\t// 未注册前的旧状态（如 interrupted）导致按钮闪烁\n\t\t\t\ttaskRuntimeState.value = {"
new_opt = "\t\t\t\t// 先乐观切到运行态，避免 refreshTaskState 读到后端异步任务\n\t\t\t\t// 未注册前的旧状态（如 interrupted）导致按钮闪烁\n\t\t\t\tlastStartTimestamp = Date.now();\n\t\t\t\ttaskRuntimeState.value = {"
if old_opt in content:
    content = content.replace(old_opt, new_opt)
    print("Step 3: lastStartTimestamp set in startTask")
else:
    print("Step 3 FAILED")
    idx = content.find("先乐观切到运行态")
    if idx > 0:
        print(repr(content[idx:idx+200]))

with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(content)
print("Done")
