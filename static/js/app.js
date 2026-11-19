/* MedAccess - scripts gerais (PWA, instalação, menu, utilidades) */
function iniciarAutocomplete(raiz) {
  raiz.querySelectorAll('[data-autocomplete]').forEach(function (box) {
    if (box.dataset.pronto) return;
    box.dataset.pronto = '1';
    var url = box.dataset.autocomplete, modo = box.dataset.modo;
    var valor = box.querySelector('[data-ac-valor]');
    var texto = box.querySelector('[data-ac-texto]');
    var lista = box.querySelector('[data-ac-lista]');
    var timer = null, itens = [], ativo = -1;

    function fechar() { lista.classList.add('d-none'); ativo = -1; }
    function escolher(it) {
      valor.value = modo === 'texto' ? it.valor : it.id;
      texto.value = modo === 'texto' ? it.valor : it.texto;
      fechar();
      box.dispatchEvent(new CustomEvent('ac:selecionado', { bubbles: true, detail: it }));
    }
    function render() {
      lista.innerHTML = '';
      if (!itens.length) {
        lista.innerHTML = '<div class="list-group-item small text-muted">Nada encontrado.</div>';
      }
      itens.forEach(function (it, i) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'list-group-item list-group-item-action small' + (i === ativo ? ' active' : '');
        b.textContent = it.texto;
        if (it.extra) {
          var s = document.createElement('div');
          s.className = 'text-muted';
          s.style.fontSize = '.75rem';
          s.textContent = it.extra;
          b.appendChild(s);
        }
        b.addEventListener('mousedown', function (e) { e.preventDefault(); escolher(it); });
        lista.appendChild(b);
      });
      lista.classList.remove('d-none');
    }
    texto.addEventListener('input', function () {
      if (modo === 'texto') { valor.value = texto.value; } else { valor.value = ''; }
      clearTimeout(timer);
      var q = texto.value.trim();
      if (q.length < 2) { fechar(); return; }
      timer = setTimeout(function () {
        fetch(url + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (d) { itens = d; ativo = -1; render(); })
          .catch(fechar);
      }, 250);
    });
    texto.addEventListener('keydown', function (e) {
      if (lista.classList.contains('d-none')) return;
      if (e.key === 'ArrowDown') { ativo = Math.min(ativo + 1, itens.length - 1); render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { ativo = Math.max(ativo - 1, 0); render(); e.preventDefault(); }
      else if (e.key === 'Enter' && ativo >= 0) { escolher(itens[ativo]); e.preventDefault(); }
      else if (e.key === 'Escape') { fechar(); }
    });
    texto.addEventListener('blur', function () {
      setTimeout(fechar, 150);
      if (modo !== 'texto' && !valor.value) { texto.value = ''; }
    });
  });
}

function iniciarNotificacoes() {
  var btn = document.getElementById('btnNotificacoes');
  if (!document.body.dataset.logado || !('Notification' in window)) { if (btn) btn.hidden = true; return; }
  function atualizarBotao() {
    if (!btn) return;
    var p = Notification.permission;
    btn.hidden = p === 'denied';
    btn.innerHTML = p === 'granted' ? '<i class="bi bi-bell-fill me-2"></i>Notificações ativadas' : '<i class="bi bi-bell me-2"></i>Ativar notificações no aparelho';
  }
  atualizarBotao();
  if (btn) btn.addEventListener('click', function () {
    if (Notification.permission === 'default') Notification.requestPermission().then(function () { atualizarBotao(); verificar(); });
  });
  var CHAVE = 'ma_notif_desde', vistos = {};
  function ler() { try { return parseFloat(localStorage.getItem(CHAVE)) || (Date.now() / 1000 - 60); } catch (e) { return Date.now() / 1000 - 60; } }
  function gravar(v) { try { localStorage.setItem(CHAVE, String(v)); } catch (e) { /* sem armazenamento */ } }
  function mostrar(it) {
    if (vistos[it.id]) return; vistos[it.id] = 1;
    var op = { body: it.texto || '', icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', tag: it.id, data: { url: it.url } };
    if (navigator.serviceWorker && navigator.serviceWorker.ready) {
      navigator.serviceWorker.ready.then(function (reg) { reg.showNotification(it.titulo, op); }).catch(function () { new Notification(it.titulo, op); });
    } else { new Notification(it.titulo, op); }
  }
  function verificar() {
    if (Notification.permission !== 'granted') return;
    fetch('/notificacoes/api/novidades/?desde=' + ler(), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (!d) return; d.itens.forEach(mostrar); gravar(d.agora); })
      .catch(function () { /* offline */ });
  }
  verificar();
  setInterval(verificar, 60000);
}

(function () {
  'use strict';

  // ---------- Service worker ----------
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function (e) {
        console.warn('Service worker não registrado:', e);
      });
    });
  }

  // ---------- Botão "Instalar aplicativo" ----------
  var promptInstalacao = null;
  var ehIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  var instalado = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

  function botoes() { return document.querySelectorAll('[data-instalar]'); }
  function mostrar(sim) {
    botoes().forEach(function (b) { b.hidden = !sim; b.classList.toggle('d-none', !sim); });
  }

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    promptInstalacao = e;
    mostrar(true);
  });
  window.addEventListener('appinstalled', function () {
    promptInstalacao = null;
    mostrar(false);
  });

  document.addEventListener('DOMContentLoaded', function () {
    if (instalado) { mostrar(false); }
    else if (ehIOS) { mostrar(true); }

    botoes().forEach(function (b) {
      b.addEventListener('click', function () {
        if (promptInstalacao) {
          promptInstalacao.prompt();
          promptInstalacao.userChoice.finally(function () { promptInstalacao = null; mostrar(false); });
        } else {
          var modal = document.getElementById('modalInstalar');
          if (modal && window.bootstrap) { new bootstrap.Modal(modal).show(); }
          else { alert('Para instalar: no menu do navegador escolha "Instalar aplicativo" ou "Adicionar à tela inicial".'); }
        }
      });
    });

    // ---------- Menu lateral (mobile) ----------
    document.querySelectorAll('[data-menu-toggle]').forEach(function (b) {
      b.addEventListener('click', function () { document.body.classList.toggle('menu-aberto'); });
    });

    // ---------- Confirmações ----------
    document.addEventListener('submit', function (e) {
      var f = e.target;
      if (f.dataset.confirm && !window.confirm(f.dataset.confirm)) { e.preventDefault(); }
    });

    // ---------- Status online/offline ----------
    function rede() {
      var el = document.getElementById('avisoOffline');
      if (el) { el.classList.toggle('d-none', navigator.onLine); }
    }
    window.addEventListener('online', rede);
    window.addEventListener('offline', rede);
    rede();

    // ---------- Notificações do aplicativo (lembretes e mensagens) ----------
    iniciarNotificacoes();

    // ---------- Autocomplete (CMED, SIGTAP, CID...) ----------
    iniciarAutocomplete(document);

    // Fecha alertas automaticamente
    setTimeout(function () {
      document.querySelectorAll('.alert-dismissible.auto-fechar').forEach(function (a) {
        if (window.bootstrap) { bootstrap.Alert.getOrCreateInstance(a).close(); }
      });
    }, 6000);
  });
})();
