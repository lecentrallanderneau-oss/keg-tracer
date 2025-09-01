// Fix 100vh sur iOS : définit --vh en px (1vh réel), et met à jour sur resize/orientation
(function(){
  function setVH() {
    const vh = window.innerHeight * 0.01;
    document.documentElement.style.setProperty('--vh', `${vh * 100}px`);
  }
  setVH();
  window.addEventListener('resize', setVH);
  window.addEventListener('orientationchange', setVH);
})();
