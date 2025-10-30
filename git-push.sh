#!/bin/bash
# Быстрый пуш изменений на GitHub

cd /root/salesbot-mvp

echo "📦 Добавление изменений..."
git add .

echo ""
echo "📝 Введите описание изменений (или нажмите Enter для автоматического):"
read -r commit_message

if [ -z "$commit_message" ]; then
    commit_message="Update: $(date '+%Y-%m-%d %H:%M')"
fi

echo ""
echo "💾 Создание коммита..."
git commit -m "$commit_message"

echo ""
echo "🚀 Пуш на GitHub..."
git push origin main

echo ""
echo "✅ Готово! Изменения запушены на:"
echo "   https://github.com/zydzymax/salesbot-mvp"
