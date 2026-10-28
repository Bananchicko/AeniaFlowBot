# Готовый FFmpeg

AeniaFlow 2.7 ищет программу через FFMPEG_PATH, в этой папке, системном PATH, затем в установленном пакете imageio-ffmpeg.

Сюда при необходимости можно положить ffmpeg для Linux или ffmpeg.exe для Windows, подходящий вашей платформе. В Linux нужны права исполнения.

Архив ffmpeg-9.0.2.tar.xz содержит исходники, а не готовую программу. Установите requirements.txt и выполните python check_setup.py. Подробности: ../FFMPEG_SETUP.md.
