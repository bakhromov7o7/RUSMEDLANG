# PDF fontlari

PDF hisobotlarda kirill (rus) va o'zbek harflari to'g'ri chiqishi uchun Unicode
TTF font kerak. `app/services/pdf_service.py` fontni quyidagi tartibda qidiradi:

1. `PDF_FONT_REGULAR` / `PDF_FONT_BOLD` env o'zgaruvchilari
2. **shu papka:** `assets/fonts/DejaVuSans.ttf` va `assets/fonts/DejaVuSans-Bold.ttf`
3. Tizim fontlari (`/usr/share/fonts/truetype/dejavu/...`, Liberation, macOS Arial)

Hech biri topilmasa PDF baribir yaratiladi, lekin kirill harflari `?` bilan
almashtiriladi.

## Serverga o'rnatish (tavsiya etilgan usul)

```bash
# Debian / Ubuntu
sudo apt-get install -y fonts-dejavu-core

# Alpine
apk add --no-cache font-dejavu
```

## Yoki fontni shu papkaga qo'yish

```bash
curl -L -o assets/fonts/DejaVuSans.ttf \
  https://github.com/dejavu-fonts/dejavu-fonts/raw/master/build/ttf/DejaVuSans.ttf
curl -L -o assets/fonts/DejaVuSans-Bold.ttf \
  https://github.com/dejavu-fonts/dejavu-fonts/raw/master/build/ttf/DejaVuSans-Bold.ttf
```

`.ttf` fayllari git'da kuzatilmaydi — ularni deploy paytida o'rnating.
