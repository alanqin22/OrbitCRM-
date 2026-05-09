import glob

html_files = glob.glob("*.html")
for f in html_files:
    with open(f, "r", encoding="utf-8") as file:
        content = file.read()
    
    # Fix single line `_IS_LOCAL` definitions missing `file:`
    if "_IS_LOCAL" in content and "protocol === 'file:'" not in content:
        # Search and replace line-by-line is safer for this
        lines = content.split('\n')
        modified = False
        for i, line in enumerate(lines):
            if ("_IS_LOCAL" in line and "window.location.hostname === 'localhost'" in line) or ("_IS_LOCAL" in line and "window.location.hostname === \"localhost\"" in line):
                if "file:" not in line:
                    # We append the file protocol check to the condition
                    # This handles both `const _IS_LOCAL = ...;` and `const _IS_LOCAL = ...`
                    if line.endswith(";"):
                        lines[i] = line[:-1] + " || window.location.protocol === 'file:';"
                    else:
                        lines[i] = line + " || window.location.protocol === 'file:';"
                    modified = True
        if modified:
            with open(f, "w", encoding="utf-8") as out_file:
                out_file.write('\n'.join(lines))
            print(f"Fixed _IS_LOCAL in {f}")
