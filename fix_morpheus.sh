#!/bin/bash
# Скрипт для исправления установки morpheus

PROJECT_ROOT="/opt/Morpheus"

if [ ! -f "$PROJECT_ROOT/morpheus" ]; then
    echo "Error: morpheus script not found at $PROJECT_ROOT/morpheus"
    exit 1
fi

# Копируем скрипт
cp "$PROJECT_ROOT/morpheus" /usr/local/bin/morpheus

# Устанавливаем правильные права
chmod +x /usr/local/bin/morpheus

# Проверяем формат файла и конвертируем если нужно (CRLF -> LF)
if file /usr/local/bin/morpheus | grep -q "CRLF"; then
    echo "Converting CRLF to LF..."
    sed -i 's/\r$//' /usr/local/bin/morpheus
fi

# Проверяем shebang
if ! head -n 1 /usr/local/bin/morpheus | grep -q "^#!/bin/bash"; then
    echo "Fixing shebang..."
    sed -i '1s|^.*|#!/bin/bash|' /usr/local/bin/morpheus
fi

echo "Morpheus script installed successfully!"
echo "Test with: sudo morpheus -help"
