"""Fix template syntax in ModelingDiscussion.vue"""
path = r"C:\Users\mojik\Desktop\mm-auto-3\MathModelAgent-main\frontend\src\components\ModelingDiscussion.vue"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix 1: Unclosed template literal
# Find the broken line with backtick then single quote
# Pattern: `progress-grow ${optionsEstimatedSec}s ease-out forwards' }"
old1 = "`progress-grow ${optionsEstimatedSec}s ease-out forwards' }"
new1 = "`progress-grow ${optionsEstimatedSec}s ease-out forwards` }"
if old1 in content:
    content = content.replace(old1, new1)
    print("Fix 1: template literal unclosed -> fixed")
else:
    print("Fix 1: NOT FOUND")

# Fix 2: Remove duplicate :style line with width
# Find line with ':style="{ width: 100 +'
idx = content.find(':style="{ width: 100 +')
if idx >= 0:
    # Go back to start of this line (or previous attribute end)
    line_start = content.rfind("\n", 0, idx) + 1
    line_end = content.find("\n", idx)
    line = content[line_start:line_end]
    print(f"Fix 2: removing line: {line.strip()[:80]}")
    # Remove the line and the newline before it
    content = content[:line_start] + content[line_end+1:]
    print("Fix 2: removed duplicate :style")
else:
    print("Fix 2: NOT FOUND")

# Fix 3: Fix percentage display
old3 = "{{ — }}%"
new3 = "{{ questionsList.length }} 个问题"
if old3 in content:
    content = content.replace(old3, new3)
    print("Fix 3: em dash text replaced")
else:
    # Try alternative
    idx = content.find("—")
    if idx >= 0:
        snippet = content[max(0,idx-20):idx+20]
        print(f"Fix 3: Found em dash at {idx}: {repr(snippet)}")
    else:
        print("Fix 3: em dash NOT FOUND")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
