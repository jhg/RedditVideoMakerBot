import json
import random
import re
import os
import subprocess
from pathlib import Path
from random import randrange
from typing import Any, Dict, Tuple

import yt_dlp
from moviepy.editor import AudioFileClip, VideoFileClip
from moviepy.video.io.ffmpeg_tools import ffmpeg_extract_subclip
from moviepy import *

from utils import settings
from utils.console import print_step, print_substep


def load_background_options():
    background_options = {}
    # Load background videos
    with open("./utils/background_videos.json") as json_file:
        background_options["video"] = json.load(json_file)

    # Load background audios
    with open("./utils/background_audios.json") as json_file:
        background_options["audio"] = json.load(json_file)

    # Remove "__comment" from backgrounds
    del background_options["video"]["__comment"]
    del background_options["audio"]["__comment"]

    for name in list(background_options["video"].keys()):
        pos = background_options["video"][name][3]

        if pos != "center":
            background_options["video"][name][3] = lambda t: ("center", pos + t)

    return background_options


def get_start_and_end_times(video_length: int, length_of_clip: int) -> Tuple[int, int]:
    """Generates a random interval of time to be used as the background of the video.

    Args:
        video_length (int): Length of the video to be generated (needed duration)
        length_of_clip (int): Length of the source background video/audio file

    Returns:
        tuple[int,int]: Start and end time of the randomized interval
    """
    # Convertir a enteros para evitar problemas de precisión
    video_length = int(video_length)
    length_of_clip = int(length_of_clip)
    
    print(f"[DEBUG] get_start_and_end_times called with video_length={video_length}, length_of_clip={length_of_clip}")
    
    # Validar que video_length es positivo
    if video_length <= 0:
        print(f"[ERROR] Invalid video_length: {video_length}. Setting minimum duration of 1 second.")
        video_length = 1
    
    # Validar que tenemos suficiente contenido para el clip
    if length_of_clip <= video_length:
        print(f"[ERROR] Background source ({length_of_clip}s) is too short for required video length ({video_length}s)")
        # Si el clip es muy corto, usamos todo el clip disponible
        if length_of_clip > 0:
            return 0, length_of_clip
        else:
            raise Exception(f"Background source ({length_of_clip}s) is too short for required video length ({video_length}s)")
    
    # Calcular el tiempo máximo de inicio para que el clip completo quepa
    # Dejamos un margen de seguridad de 2 segundos
    margin = min(2, length_of_clip // 10)  # Margen adaptativo
    max_start_time = length_of_clip - video_length - margin
    
    # Asegurar que tenemos al menos un margen mínimo
    if max_start_time < 0:
        print(f"[WARNING] Insufficient margin. Using available clip length.")
        max_start_time = max(0, length_of_clip - video_length)
    
    # Seleccionar tiempo de inicio aleatorio con margen de seguridad
    # Asegurar que el rango sea válido (al menos 1 segundo de diferencia)
    if max_start_time <= 0:
        start_time = 0
    else:
        start_time = random.randint(0, max_start_time)
    
    end_time = start_time + video_length
    
    # Asegurar que no excedemos la duración del clip
    if end_time > length_of_clip:
        end_time = length_of_clip
        start_time = max(0, end_time - video_length)
    
    # Validación final para asegurar rangos válidos
    if end_time <= start_time:
        print(f"[ERROR] Invalid time calculation: start={start_time}, end={end_time}, video_length={video_length}")
        # Último recurso: usar el inicio del clip
        start_time = 0
        end_time = min(video_length, length_of_clip)
        
        if end_time <= start_time:
            raise Exception(f"Unable to create valid time range from clip of {length_of_clip}s for video of {video_length}s")
    
    print(f"[DEBUG] Generated valid time range: start={start_time}, end={end_time}, duration={end_time - start_time}")
    return start_time, end_time


def get_background_config(mode: str):
    """Fetch the background/s configuration"""
    try:
        choice = str(settings.config["settings"]["background"][f"background_{mode}"]).casefold()
    except AttributeError:
        print_substep("No background selected. Picking random background'")
        choice = None

    # Handle default / not supported background using default option.
    # Default : pick random from supported background.
    if not choice or choice not in background_options[mode]:
        choice = random.choice(list(background_options[mode].keys()))

    return background_options[mode][choice]


def download_background_video(background_config: Tuple[str, str, str, Any]):
    """Downloads the background/s video from YouTube."""
    Path("./assets/backgrounds/video/").mkdir(parents=True, exist_ok=True)
    # note: make sure the file name doesn't include an - in it
    uri, filename, credit, _ = background_config
    if Path(f"assets/backgrounds/video/{credit}-{filename}").is_file():
        return
    print_step(
        "We need to download the backgrounds videos. they are fairly large but it's only done once. 😎"
    )
    print_substep("Downloading the backgrounds videos... please be patient 🙏 ")
    print_substep(f"Downloading {filename} from {uri}")
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]",
        "outtmpl": f"assets/backgrounds/video/{credit}-{filename}",
        "retries": 10,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(uri)
    print_substep("Background video downloaded successfully! 🎉", style="bold green")


def download_background_audio(background_config: Tuple[str, str, str]):
    """Downloads the background/s audio from YouTube."""
    Path("./assets/backgrounds/audio/").mkdir(parents=True, exist_ok=True)
    # note: make sure the file name doesn't include an - in it
    uri, filename, credit = background_config
    if Path(f"assets/backgrounds/audio/{credit}-{filename}").is_file():
        return
    print_step(
        "We need to download the backgrounds audio. they are fairly large but it's only done once. 😎"
    )
    print_substep("Downloading the backgrounds audio... please be patient 🙏 ")
    print_substep(f"Downloading {filename} from {uri}")
    ydl_opts = {
        "outtmpl": f"./assets/backgrounds/audio/{credit}-{filename}",
        "format": "bestaudio/best",
        "extract_audio": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([uri])

    print_substep("Background audio downloaded successfully! 🎉", style="bold green")


def chop_background(background_config: Dict[str, Tuple], video_length: int, reddit_object: dict):
    """Generates the background audio and footage to be used in the video and writes it to assets/temp/background.mp3 and assets/temp/background.mp4

    Args:
        background_config (Dict[str,Tuple]]) : Current background configuration
        video_length (int): Length of the clip where the background footage is to be taken out of
    """
    id = re.sub(r"[^\w\s-]", "", reddit_object["thread_id"])

    if settings.config["settings"]["background"][f"background_audio_volume"] == 0:
        print_step("Volume was set to 0. Skipping background audio creation . . .")
    else:
        print_step("Finding a spot in the backgrounds audio to chop...✂️")
        print(background_config)
        audio_choice = f"{background_config['audio'][2]}-{background_config['audio'][1]}"
        audio_file_path = f"assets/backgrounds/audio/{audio_choice}"
        print(f"[DEBUG] {audio_file_path}")
        
        # Usar FFprobe para obtener la duración real del archivo
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
                '-of', 'default=noprint_wrappers=1:nokey=1', audio_file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            audio_duration = float(result.stdout.strip())
            print(f"[DEBUG] FFProbe detected audio duration: {audio_duration}")
            
            # Verificar que tenemos suficiente duración
            if audio_duration <= video_length + 2:  # +2 para margen de seguridad
                print_substep(f"Audio duration ({audio_duration}s) is too short for video length ({video_length}s). Creating silent audio.")
                subprocess.run([
                    'ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo', 
                    '-t', str(video_length), f'assets/temp/{id}/background.mp3'
                ], check=True)
                print_substep("Created silent background audio successfully")
            else:
                # Usar la función corregida para calcular tiempos
                start_time_audio, end_time_audio = get_start_and_end_times(video_length, int(audio_duration))
                
                print(f"[DEBUG] Using audio segment from {start_time_audio} to {end_time_audio}")
                
                # SOLUCIÓN AL ISSUE #2004: Usar FFmpeg directamente para MP3
                # en lugar de MoviePy para evitar problemas de duración incorrecta
                try:
                    print_substep("Extracting audio with FFmpeg (avoiding MoviePy MP3 duration issue)...")
                    subprocess.run([
                        'ffmpeg', '-y', 
                        '-ss', str(start_time_audio), 
                        '-i', audio_file_path, 
                        '-t', str(video_length),
                        '-c:a', 'mp3', 
                        '-q:a', '0', 
                        f'assets/temp/{id}/background.mp3'
                    ], check=True, capture_output=True)
                    print_substep("Audio extraction with FFmpeg succeeded!")
                    
                    # Verificar que el archivo generado es válido
                    if not os.path.exists(f'assets/temp/{id}/background.mp3') or os.path.getsize(f'assets/temp/{id}/background.mp3') == 0:
                        raise Exception("Generated audio file is empty or doesn't exist")
                        
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] FFMPEG extraction failed: {e}")
                    print(f"[WARNING] FFmpeg stderr: {e.stderr.decode() if e.stderr else 'No stderr'}")
                    # Fallback: crear audio silencioso
                    subprocess.run([
                        'ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo', 
                        '-t', str(video_length), f'assets/temp/{id}/background.mp3'
                    ], check=True)
                    print_substep("Created silent background audio as fallback")
                    
        except Exception as e:
            print(f"[ERROR] Failed to process audio: {str(e)}")
            # Fallback final: crear audio silencioso
            subprocess.run([
                'ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo', 
                '-t', str(video_length), f'assets/temp/{id}/background.mp3'
            ], check=True)
            print_substep("Created silent background audio as final fallback")

    print_step("Finding a spot in the backgrounds video to chop...✂️")
    video_choice = f"{background_config['video'][2]}-{background_config['video'][1]}"
    video_file_path = f"assets/backgrounds/video/{video_choice}"
    
    try:
        # Obtener duración del video con FFprobe
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
            '-of', 'default=noprint_wrappers=1:nokey=1', video_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        video_duration = float(result.stdout.strip())
        print(f"[DEBUG] FFProbe detected video duration: {video_duration}")
        
        if video_duration <= video_length + 2:  # +2 para margen de seguridad
            raise ValueError(f"Video duration ({video_duration}s) is too short for required length ({video_length}s)")
            
        # Usar la función corregida para calcular tiempos
        start_time_video, end_time_video = get_start_and_end_times(video_length, int(video_duration))
        
        print(f"[DEBUG] Using video segment from {start_time_video} to {end_time_video}")
        
        # Usar FFmpeg directamente para video también
        try:
            subprocess.run([
                'ffmpeg', '-y',
                '-ss', str(start_time_video), 
                '-i', video_file_path, 
                '-t', str(video_length),
                '-c:v', 'libx264', 
                '-preset', 'fast', 
                '-crf', '22',
                f'assets/temp/{id}/background.mp4'
            ], check=True, capture_output=True)
            
            # Verificar que el archivo de video es válido
            if not os.path.exists(f'assets/temp/{id}/background.mp4') or os.path.getsize(f'assets/temp/{id}/background.mp4') == 0:
                raise Exception("Generated video file is empty or doesn't exist")
                
            # Verificar duración del video generado
            verify_result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
                '-of', 'default=noprint_wrappers=1:nokey=1', f'assets/temp/{id}/background.mp4'
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            generated_duration = float(verify_result.stdout.strip())
            if generated_duration <= 0:
                raise Exception(f"Generated video has invalid duration: {generated_duration}")
                
            print_substep("Background video chopped successfully with FFmpeg!")
            
        except subprocess.CalledProcessError as e:
            print(f"[WARNING] Direct FFmpeg approach for video failed: {e}")
            print(f"[WARNING] FFmpeg stderr: {e.stderr.decode() if e.stderr else 'No stderr'}")
            
            # Fallback con MoviePy solo si FFmpeg falla completamente
            try:
                print_substep("Trying MoviePy as fallback for video...")
                ffmpeg_extract_subclip(
                    video_file_path,
                    start_time_video,
                    start_time_video + video_length,
                    targetname=f"assets/temp/{id}/background.mp4",
                )
                print_substep("Background video chopped successfully with MoviePy fallback!")
            except Exception as moviepy_error:
                print(f"[ERROR] MoviePy fallback also failed: {moviepy_error}")
                raise Exception("All video processing methods failed")
            
    except Exception as e:
        print(f"[ERROR] Failed to process video: {str(e)}")
        raise
        
    print_substep("Background chopping completed successfully!", style="bold green")
    return background_config["video"][2]


# Create a tuple for downloads background (background_audio_options, background_video_options)
background_options = load_background_options()
