"""One continuous RTMP audio clock over the prepared HLS news playlist."""

from urllib.parse import urlsplit


def command(source, destination, realtime=True):
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-nostats",
            "-stats_period", "1", "-progress", "pipe:1", "-threads", "1", "-filter_threads", "1",
            "-fflags", "+genpts+discardcorrupt", "-dts_delta_threshold", "1"]
    if urlsplit(source).scheme in {"http", "https"}:
        args += ["-rw_timeout", "15000000", "-reconnect", "1", "-reconnect_streamed", "1",
                 "-reconnect_delay_max", "5"]
    if realtime:
        args += ["-live_start_index", "-3", "-seg_max_retry", "2", "-re"]
    args += ["-i", source, "-map", "0:v:0", "-map", "0:a:0", "-sn", "-dn",
             "-c:v", "copy",
             # async=1 fills gaps/trims overlaps; it does not stretch speech.
             # Count output samples after that correction to keep AAC timestamps
             # strictly increasing across independently encoded input clips.
             "-af", "aresample=48000:async=1:first_pts=0:min_hard_comp=0.020,asetpts=N/SR/TB",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-threads:a", "1",
             "-avoid_negative_ts", "make_zero", "-max_muxing_queue_size", "256"]
    target = urlsplit(destination)
    if target.scheme == "rtmps":
        args += ["-rw_timeout", "15000000", "-tls_verify", "1", "-verifyhost", target.hostname,
                 "-ca_file", "/etc/ssl/certs/ca-certificates.crt"]
    args += ["-f", "flv", "-flvflags", "no_duration_filesize", destination]
    return args
