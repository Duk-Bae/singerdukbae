import discord
from discord.ext import commands
import yt_dlp
import asyncio
import random

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

ytdlp_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "default_search": "ytsearch",
    "noplaylist": True,
}

ffmpeg_opts = {
    "options": "-vn"
}

song_queue = []          # url 리스트
song_titles = []         # {title, thumbnail}
song_queue_channel_id = None
song_queue_message_id = None
current_song = None
loop_enabled = False

# --------------------
# Embed helpers
# --------------------
def base_embed(title, description=""):
    return discord.Embed(title=title, description=description, color=0xa0cbd6)

def make_song_queue_embed():
    if not song_titles:
        desc = "현재 큐에 노래가 없습니다."
    else:
        desc = "\n".join(
            f"{i}. {song['title']}"
            for i, song in enumerate(song_titles, start=1)
        )
    return base_embed("🎶 대기열", desc)

def make_now_playing_embed():
    if not current_song:
        return None

    embed = base_embed("🎧 지금 재생 중", f"**{current_song['title']}**")
    if current_song.get("thumbnail"):
        embed.set_thumbnail(url=current_song["thumbnail"])
    return embed

async def update_song_queue_panel(guild):
    global song_queue_message_id

    if song_queue_channel_id is None:
        return

    channel = guild.get_channel(song_queue_channel_id)
    if not channel:
        return

    view = MusicControlView()

    embeds = []
    now = make_now_playing_embed()
    if now:
        embeds.append(now)
    embeds.append(make_song_queue_embed())

    if song_queue_message_id:
        try:
            msg = await channel.fetch_message(song_queue_message_id)
            await msg.edit(embeds=embeds, view=view)
            return
        except:
            pass

    msg = await channel.send(embeds=embeds, view=view)
    song_queue_message_id = msg.id

# --------------------
# 음악 재생 로직 (핵심 수정)
# --------------------
async def play_next(ctx):
    global current_song

    if not song_queue:
        current_song = None
        await update_song_queue_panel(ctx.guild)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        return

    url = song_queue.pop(0)
    song = song_titles.pop(0)

    current_song = song

    if loop_enabled:
        song_queue.append(url)
        song_titles.append(song)

    await update_song_queue_panel(ctx.guild)

    source = discord.FFmpegPCMAudio(url, **ffmpeg_opts)
    ctx.voice_client.play(
        source,
        after=lambda e: asyncio.run_coroutine_threadsafe(
            play_next(ctx), bot.loop
        )
    )

# --------------------
# 버튼 UI
# --------------------
class MusicControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏸ 일시정지", style=discord.ButtonStyle.gray)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ 일시정지", ephemeral=True)
        else:
            await interaction.response.send_message("재생 중이 아니에요.", ephemeral=True)

    @discord.ui.button(label="▶ 재개", style=discord.ButtonStyle.green)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶ 재개", ephemeral=True)
        else:
            await interaction.response.send_message("멈춰있는 노래가 없어요.", ephemeral=True)

    @discord.ui.button(label="⏭ 스킵", style=discord.ButtonStyle.blurple)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭ 스킵", ephemeral=True)
        else:
            await interaction.response.send_message("재생 중이 아니에요.", ephemeral=True)

    @discord.ui.button(label="⏹ 정지", style=discord.ButtonStyle.red)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            await interaction.response.send_message("👋 종료", ephemeral=True)

    @discord.ui.button(label="🔁 반복", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        global loop_enabled
        loop_enabled = not loop_enabled
        await interaction.response.send_message(
            f"반복 모드 {'켜짐 🔁' if loop_enabled else '꺼짐 ❌'}",
            ephemeral=True
        )

    @discord.ui.button(label="🔀 셔플", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(song_queue) < 2:
            await interaction.response.send_message("셔플할 노래가 부족해요.", ephemeral=True)
            return
        combined = list(zip(song_queue, song_titles))
        random.shuffle(combined)
        song_queue[:], song_titles[:] = zip(*combined)
        await update_song_queue_panel(interaction.guild)
        await interaction.response.send_message("🔀 셔플 완료!", ephemeral=True)

# --------------------
# !play
# --------------------
@bot.command()
async def play(ctx, *, search: str):
    if not ctx.author.voice:
        msg = await ctx.send("❗ 음성 채널에 먼저 들어가 주세요.")
        await asyncio.sleep(3)
        await msg.delete()
        await ctx.message.delete()
        return

    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
        info = ydl.extract_info(search, download=False)
        if "entries" in info:
            info = info["entries"][0]

    song_queue.append(info["url"])
    song_titles.append({
        "title": info["title"],
        "thumbnail": info.get("thumbnail")
    })

    await update_song_queue_panel(ctx.guild)

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

    try:
        await ctx.message.delete()
    except:
        pass

# --------------------
# !queue
# --------------------
@bot.command()
async def queue(ctx):
    await ctx.send(embed=make_song_queue_embed())

# --------------------
# !leave
# --------------------
@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 나갔어요.")

# --------------------
# !도움말
# --------------------
@bot.command()
async def 도움말(ctx):
    embed = base_embed(
        "📖 도움말",
        "**!세팅** : 봇 전용 채널 생성\n"
        "**!play** : 노래 재생\n"
        "**!queue** : 대기열 보기\n"
        "**!leave** : 음성 채널 나가기"
    )
    await ctx.send(embed=embed)

# --------------------
# !세팅
# --------------------
@bot.command(name="세팅")
@commands.has_permissions(manage_channels=True)
async def setup(ctx):
    global song_queue_channel_id, song_queue_message_id

    channel = discord.utils.get(ctx.guild.text_channels, name="🎵-싱어송라이터덕배")
    if not channel:
        channel = await ctx.guild.create_text_channel("🎵-싱어송라이터덕배")

    song_queue_channel_id = channel.id
    song_queue_message_id = None

    await update_song_queue_panel(ctx.guild)
    await ctx.send("✅ 세팅 완료")

# --------------------
# 실행
# --------------------
@bot.event
async def on_ready():
    print("=" * 40)
    print(f"✅ 준비 완료: {bot.user}")
 
bot.run("MTMyMzA4MDQ4Njc2NzAzODY3NA.GJMZBR.xQTmPbI-BxnVUxKkPO1Svx2o0yC2Fe4ZjLZ2Zs")

