"""
Video composition engine using MoviePy.
Stitches generated clips with per-scene voiceover sync, text overlays,
and optional background music.
"""

import uuid
from pathlib import Path

from .video_dataclasses import (
    VideoAdConcept,
    GeneratedClip,
    GeneratedVoiceover,
    ComposedVideo,
)


class VideoComposer:
    """
    Compose final video ads from clips, audio, and text overlays using MoviePy.

    Audio sync strategy: each scene gets its own voiceover clip, aligned to
    start at that scene's offset in the timeline. If a voiceover is longer than
    its scene, the scene is extended to fit. This ensures spoken words match
    the visuals they describe.

    Requires: moviepy>=2.0.0 and ffmpeg installed on the system.
    """

    def __init__(self, output_dir: str = "output/videos/final"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compose(
        self,
        concept: VideoAdConcept,
        clips: list[GeneratedClip],
        scene_voiceovers: list[GeneratedVoiceover | None] | None = None,
        cta_voiceover: GeneratedVoiceover | None = None,
        background_music_path: str | None = None,
        music_volume: float = 0.15,
    ) -> ComposedVideo:
        """
        Compose a final video with per-scene audio sync.

        Args:
            concept: The video ad concept
            clips: Generated video clips (one per scene)
            scene_voiceovers: Per-scene voiceover audio (same length as clips, None entries = no VO)
            cta_voiceover: Separate voiceover for the CTA (overlaid on last scene)
            background_music_path: Optional background music file
            music_volume: Volume for background music (0.0-1.0)
        """
        from moviepy import (
            VideoFileClip,
            AudioFileClip,
            CompositeAudioClip,
            concatenate_videoclips,
        )

        if not clips:
            raise ValueError("No clips provided for composition")

        if scene_voiceovers is None:
            scene_voiceovers = [None] * len(clips)

        # 1. Load clips, adjust durations to match voiceover, add text overlays
        processed_clips = []
        for i, gen_clip in enumerate(clips):
            video = VideoFileClip(gen_clip.video_path)
            target_dur = gen_clip.scene.duration_seconds

            # If this scene has voiceover, ensure the clip is long enough
            vo = scene_voiceovers[i] if i < len(scene_voiceovers) else None
            if vo and vo.duration_seconds > target_dur:
                # Extend target so the voiceover fits within this scene
                target_dur = vo.duration_seconds + 0.3  # small padding

            # Trim or freeze-frame to match target duration
            if video.duration > target_dur:
                video = video.subclipped(0, target_dur)
            elif video.duration < target_dur:
                # Freeze the last frame to extend
                video = video.with_duration(target_dur)

            # Add text overlay if present
            if gen_clip.scene.text_overlay:
                video = self._add_text_overlay(
                    video,
                    gen_clip.scene.text_overlay,
                    gen_clip.scene.text_overlay_position,
                )

            processed_clips.append(video)

        # 2. Add CTA text overlay to the last clip
        if concept.cta_text and processed_clips:
            last_clip = processed_clips[-1]
            processed_clips[-1] = self._add_text_overlay(
                last_clip,
                concept.cta_text,
                position="center",
                fontsize=48,
            )

        # 3. Concatenate all clips
        final = concatenate_videoclips(processed_clips, method="compose")

        # 4. Build audio timeline with per-scene sync
        audio_clips = []

        # Calculate each scene's start time in the concatenated timeline
        scene_starts = []
        t = 0.0
        for clip in processed_clips:
            scene_starts.append(t)
            t += clip.duration

        # Per-scene voiceovers, each starting at its scene's offset
        for i, vo in enumerate(scene_voiceovers):
            if vo and vo.audio_path:
                try:
                    vo_audio = AudioFileClip(vo.audio_path)
                    # Trim if somehow longer than the scene
                    scene_dur = processed_clips[i].duration
                    if vo_audio.duration > scene_dur:
                        vo_audio = vo_audio.subclipped(0, scene_dur)
                    # Offset to start at this scene's position in the timeline
                    vo_audio = vo_audio.with_start(scene_starts[i])
                    audio_clips.append(vo_audio)
                except Exception as e:
                    print(f"  Warning: Could not load voiceover for scene {i + 1}: {e}")

        # CTA voiceover on the last scene
        if cta_voiceover and cta_voiceover.audio_path and processed_clips:
            try:
                cta_audio = AudioFileClip(cta_voiceover.audio_path)
                last_scene_start = scene_starts[-1]
                last_scene_dur = processed_clips[-1].duration
                # Place CTA voiceover at end of last scene (offset so it finishes near the end)
                cta_start = last_scene_start + max(0, last_scene_dur - cta_audio.duration - 0.2)
                cta_audio = cta_audio.with_start(cta_start)
                audio_clips.append(cta_audio)
            except Exception as e:
                print(f"  Warning: Could not load CTA voiceover: {e}")

        # Background music
        if background_music_path:
            try:
                music = AudioFileClip(background_music_path)
                if music.duration > final.duration:
                    music = music.subclipped(0, final.duration)
                music = music.with_volume_scaled(music_volume)
                audio_clips.append(music)
            except Exception as e:
                print(f"  Warning: Could not load background music: {e}")

        # Set composite audio
        if audio_clips:
            final = final.with_audio(CompositeAudioClip(audio_clips))

        # 5. Export
        safe_title = "".join(
            c if c.isalnum() or c in " -_" else "_"
            for c in concept.title
        )[:40]
        filename = f"{safe_title}_{uuid.uuid4().hex[:6]}.mp4"
        output_path = str(self.output_dir / filename)

        print(f"  Composing video: {output_path}")
        final.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=24,
            logger=None,  # Suppress moviepy progress bars
        )

        # Generate thumbnail
        thumbnail_path = self._generate_thumbnail(output_path, final)

        # Calculate total cost
        total_cost = sum(c.generation_cost for c in clips)

        # Clean up
        final.close()
        for clip in processed_clips:
            clip.close()

        return ComposedVideo(
            concept=concept,
            clips=clips,
            voiceover=None,  # Per-scene VOs tracked in clips
            output_path=output_path,
            thumbnail_path=thumbnail_path,
            total_cost=total_cost,
            total_duration=final.duration,
        )

    def _add_text_overlay(
        self,
        clip,
        text: str,
        position: str = "bottom",
        fontsize: int = 36,
        color: str = "white",
        bg_opacity: float = 0.5,
    ):
        """Add styled text overlay to a video clip."""
        from moviepy import TextClip, CompositeVideoClip

        txt = TextClip(
            text=text,
            font_size=fontsize,
            color=color,
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=2,
            size=(clip.w * 0.9, None),  # 90% width, auto height
            method="caption",
        ).with_duration(clip.duration)

        # Position mapping
        positions = {
            "top": ("center", 20),
            "center": ("center", "center"),
            "bottom": ("center", clip.h - 80),
        }
        pos = positions.get(position, ("center", "center"))

        return CompositeVideoClip([clip, txt.with_position(pos)])

    def _generate_thumbnail(self, video_path: str, video_clip=None) -> str | None:
        """Extract a frame from the video as a thumbnail."""
        try:
            from moviepy import VideoFileClip

            if video_clip is None:
                video_clip = VideoFileClip(video_path)

            # Get frame at 1 second (or halfway if shorter)
            t = min(1.0, video_clip.duration / 2)
            thumb_path = video_path.replace(".mp4", "_thumb.jpg")
            video_clip.save_frame(thumb_path, t=t)

            return thumb_path
        except Exception as e:
            print(f"  Warning: Could not generate thumbnail: {e}")
            return None
