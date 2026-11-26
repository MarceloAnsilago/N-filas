(() => {
  let player = null;
  let ready = false;
  let announcing = false;
  let originalVolume = null;
  let video = null;
  let iframe = null;

  function lowerVolume() {
    if (video) {
      if (originalVolume === null) originalVolume = video.volume;
      video.volume = Math.min(originalVolume, 0.15);
    } else if (ready) {
      if (originalVolume === null) originalVolume = player.getVolume();
      player.setVolume(Math.min(originalVolume, 15));
    }
  }

  window.painelMedia = {
    select(nextVideo, nextIframe = null) {
      const wasAnnouncing = announcing;
      this.restore();
      if (player) player.destroy();
      player = null;
      ready = false;
      video = nextVideo;
      iframe = nextIframe;
      announcing = wasAnnouncing;
      if (announcing) lowerVolume();
      if (iframe) setupYouTube(iframe);
    },
    lower() {
      announcing = true;
      lowerVolume();
    },
    restore() {
      announcing = false;
      if (originalVolume === null) return;
      if (video) video.volume = originalVolume;
      else if (ready) player.setVolume(originalVolume);
      originalVolume = null;
    },
  };

  function setupYouTube(frame) {
    const url = new URL(frame.src, location.href);
    if (!['youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(url.hostname)) return;
    url.searchParams.set('enablejsapi', '1');
    url.searchParams.set('origin', location.origin);
    frame.src = url.toString();

    function initialize() {
      if (iframe !== frame) return;
      player = new YT.Player(frame, {
        events: {
          onReady() {
            if (iframe !== frame) return;
            ready = true;
            if (announcing) lowerVolume();
          },
        },
      });
    }
    if (window.YT?.Player) initialize();
    else {
      const loading = Boolean(window.onYouTubeIframeAPIReady);
      window.onYouTubeIframeAPIReady = initialize;
      if (loading) return;
      const script = document.createElement('script');
      script.src = 'https://www.youtube.com/iframe_api';
      document.head.appendChild(script);
    }
  }
  window.painelMedia.select(document.querySelector('.video video'), document.querySelector('.video iframe'));
})();
