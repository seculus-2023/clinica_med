/* Painel de senhas para TV. Escrito em ES5, sem dependências, para funcionar em navegadores de TV antigos. */
(function () {
  'use strict';
  var INTERVALO = 2000, LIMITE_FALA = 12000;
  var el = function (id) { return document.getElementById(id); };
  var tv = el('tv'), url = tv.getAttribute('data-url');
  var ultimoId = null, fila = [], ocupado = false, somAtivo = false, audio = null, falhas = 0;
  var voz = null, cfg = { voz: true, repeticoes: 2 }, desvioRelogio = null;
  var sintese = window.speechSynthesis || null;

  function escolherVoz() {
    if (!sintese) return;
    var vozes = sintese.getVoices() || [], i, l;
    voz = null;
    for (i = 0; i < vozes.length; i++) {
      l = (vozes[i].lang || '').replace('_', '-').toLowerCase();
      if (l === 'pt-br') { voz = vozes[i]; break; }
      if (!voz && l.indexOf('pt') === 0) voz = vozes[i];
    }
    atualizarEstado();
  }

  function atualizarEstado(erro) {
    var aviso = '';
    if (erro) aviso = 'Sem conexão: tentando novamente';
    else if (somAtivo && cfg.voz && (!sintese || !voz)) aviso = 'TV sem voz em português: só o aviso sonoro';
    el('estado').textContent = aviso;
    el('estado').hidden = !aviso;
  }

  function relogio() {
    if (desvioRelogio === null) return;
    // data deslocada para a hora da clínica: por isso a leitura é feita em UTC
    var d = new Date(Date.now() + desvioRelogio), h = d.getUTCHours(), m = d.getUTCMinutes();
    el('hora').textContent = (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
    var dias = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado'];
    var dia = d.getUTCDate(), mes = d.getUTCMonth() + 1;
    el('data').textContent = dias[d.getUTCDay()] + ', ' + (dia < 10 ? '0' : '') + dia + '/' + (mes < 10 ? '0' : '') + mes;
  }

  function mostrarAtual(item) {
    el('codigo').textContent = item ? item.codigo : '---';
    el('local').textContent = item ? item.local : 'Aguardando chamada';
    el('pref').hidden = !(item && item.preferencial);
  }

  function mostrarLista(itens) {
    var ol = el('lista');
    while (ol.firstChild) ol.removeChild(ol.firstChild);
    for (var i = 0; i < itens.length; i++) {
      var li = document.createElement('li'), b = document.createElement('b'), s = document.createElement('span');
      b.textContent = itens[i].codigo;
      s.textContent = itens[i].local;
      li.appendChild(b); li.appendChild(s); ol.appendChild(li);
    }
  }

  function destacar() {
    var c = el('cartaoAtual');
    c.className = 'atual';
    void c.offsetWidth;
    c.className = 'atual chamando';
    setTimeout(function () { c.className = 'atual'; }, 3000);
  }

  function aviso(fim) {
    if (!audio) { fim(); return; }
    try {
      if (audio.state === 'suspended') audio.resume();
      var t = audio.currentTime + 0.02;
      [[784, 0], [1047, 0.32]].forEach(function (n) {
        var o = audio.createOscillator(), g = audio.createGain();
        o.type = 'sine'; o.frequency.value = n[0];
        g.gain.setValueAtTime(0.0001, t + n[1]);
        g.gain.exponentialRampToValueAtTime(0.5, t + n[1] + 0.03);
        g.gain.exponentialRampToValueAtTime(0.0001, t + n[1] + 0.5);
        o.connect(g); g.connect(audio.destination);
        o.start(t + n[1]); o.stop(t + n[1] + 0.55);
      });
    } catch (e) { /* segue sem o aviso sonoro */ }
    setTimeout(fim, 950);
  }

  function falar(texto, vezes, fim) {
    if (!somAtivo || !cfg.voz || !sintese || !voz || vezes <= 0) { fim(); return; }
    var concluido = false;
    var seguir = function () {
      if (concluido) return;
      concluido = true;
      clearTimeout(guarda);
      setTimeout(function () { falar(texto, vezes - 1, fim); }, 450);
    };
    var guarda = setTimeout(function () { sintese.cancel(); seguir(); }, LIMITE_FALA);
    var u = new SpeechSynthesisUtterance(texto);
    u.voice = voz; u.lang = voz.lang || 'pt-BR'; u.rate = 0.9; u.volume = 1;
    u.onend = seguir; u.onerror = seguir;
    sintese.speak(u);
  }

  function processarFila() {
    if (ocupado || !fila.length) return;
    ocupado = true;
    var item = fila.shift();
    mostrarAtual(item);
    destacar();
    var terminar = function () { ocupado = false; processarFila(); };
    if (!somAtivo) { setTimeout(terminar, 1500); return; }
    aviso(function () { falar(item.texto, cfg.repeticoes, terminar); });
  }

  function aplicar(d) {
    cfg.voz = d.voz; cfg.repeticoes = d.repeticoes;
    desvioRelogio = d.relogio_ms - Date.now();
    relogio();
    el('titulo').textContent = d.titulo;
    el('mensagem').textContent = d.mensagem;
    el('aguardando').textContent = d.aguardando;
    mostrarLista(d.anteriores);
    if (ultimoId !== null && d.novas.length) {
      fila = fila.concat(d.novas);
      processarFila();
    } else if (!ocupado && !fila.length) {
      mostrarAtual(d.atual);
    }
    ultimoId = d.novas.length ? d.novas[d.novas.length - 1].id : Math.max(ultimoId || 0, d.ultimo_id);
  }

  function consultar() {
    var x = new XMLHttpRequest(), fim = false;
    var proximo = function (ok) {
      if (fim) return;
      fim = true;
      falhas = ok ? 0 : falhas + 1;
      atualizarEstado(falhas >= 3);
      setTimeout(consultar, ok ? INTERVALO : Math.min(INTERVALO * (falhas + 1), 15000));
    };
    x.open('GET', url + (ultimoId !== null ? '?desde=' + ultimoId : ''), true);
    x.timeout = 8000;
    x.onload = function () {
      if (x.status !== 200) { proximo(false); return; }
      try { aplicar(JSON.parse(x.responseText)); proximo(true); } catch (e) { proximo(false); }
    };
    x.onerror = x.ontimeout = function () { proximo(false); };
    x.send();
  }

  function manterLigada() {
    if (navigator.wakeLock && navigator.wakeLock.request) {
      navigator.wakeLock.request('screen').catch(function () {});
    }
  }

  function ativarSom() {
    if (somAtivo) return;
    somAtivo = true;
    el('ativar').hidden = true;
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) { try { audio = new Ctx(); audio.resume && audio.resume(); } catch (e) { audio = null; } }
    var raiz = document.documentElement;
    var cheia = raiz.requestFullscreen || raiz.webkitRequestFullscreen;
    if (cheia) { try { var p = cheia.call(raiz); if (p && p.catch) p.catch(function () {}); } catch (e) { /* opcional */ } }
    manterLigada();
    escolherVoz();
    aviso(function () { falar('Som do painel ativado.', 1, function () {}); });
  }

  el('ativar').addEventListener('click', ativarSom);
  document.addEventListener('keydown', function (e) {
    if (!somAtivo && (e.key === 'Enter' || e.keyCode === 13 || e.key === ' ')) { e.preventDefault(); ativarSom(); }
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden && somAtivo) manterLigada(); });
  if (sintese) {
    escolherVoz();
    if (sintese.addEventListener) sintese.addEventListener('voiceschanged', escolherVoz);
    else sintese.onvoiceschanged = escolherVoz;
  }
  relogio();
  setInterval(relogio, 1000);
  consultar();
})();
