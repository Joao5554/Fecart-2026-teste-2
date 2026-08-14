/* Interface do projeto Fecart 2026.
   JavaScript puro, sem bibliotecas: tudo roda localmente, junto com a API. */

// Servida pela própria API (http://127.0.0.1:8000/app), a origem é a mesma.
// Aberta com Live Server ou direto do arquivo, aponta para o uvicorn.
const API = (location.protocol === "file:" || location.port !== "8000")
  ? "http://127.0.0.1:8000"
  : location.origin;

const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
               "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

const CORES = { baixo: "#2E7D32", medio: "#F9A825", alto: "#C62828" };

// Tipos de desastre, iguais aos de src/esquema.py (GRUPOS_COBRADE).
// Ficam aqui para o formulário funcionar mesmo antes de a API responder.
// O teste testes/test_frontend.py falha se esta lista sair de sincronia
// com o esquema do projeto.
const TIPOS_DESASTRE = [
  "ESTIAGEM_SECA", "INUNDACAO", "ENXURRADA", "ALAGAMENTO", "CHUVAS_INTENSAS",
  "DESLIZAMENTO", "VENDAVAL_CICLONE", "GRANIZO", "INCENDIO_FLORESTAL", "EROSAO",
];

const EXPLICACAO = {
  baixo: "Nenhuma ocorrência esperada para este mês, segundo o histórico.",
  medio: "Ocorrência provável, sem sinal de gravidade excepcional.",
  alto: "Ocorrência provável com gravidade alta — o tipo de caso que costuma "
      + "gerar decreto de emergência ou vítimas.",
};

// Nomes amigáveis das variáveis históricas, para a caixa "como o modelo chegou a isso".
const ROTULOS = {
  ocorrencias_12m: "Ocorrências nos últimos 12 meses",
  ocorrencias_24m: "Ocorrências nos últimos 24 meses",
  ocorrencias_60m: "Ocorrências nos últimos 5 anos",
  ocorrencias_total_historico: "Total já registrado no município",
  meses_desde_ultima_ocorrencia: "Meses desde a última ocorrência",
  ja_ocorreu: "Já ocorreu alguma vez",
  anos_de_historico: "Anos de histórico",
  ocorrencias_mesmo_mes_historico: "Vezes que ocorreu neste mesmo mês",
  reconhecimentos_historico: "Emergências reconhecidas",
  mortos_historico: "Mortos em ocorrências anteriores",
  afetados_historico: "Afetados em ocorrências anteriores",
  prejuizo_historico_log: "Prejuízo acumulado (escala log)",
  ocorrencias_municipio_12m: "Ocorrências de qualquer tipo (12 meses)",
  ocorrencias_uf_grupo_12m: "Ocorrências deste tipo na UF (12 meses)",
  // Faixas disjuntas, usadas só na análise de odds ratio.
  ocorrencias_13_a_24m: "Ocorrências entre 13 e 24 meses atrás",
  ocorrencias_25_a_60m: "Ocorrências entre 25 e 60 meses atrás",
};

let municipioEscolhido = null;
let temporizadorBusca = null;

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------

async function iniciar() {
  // Meses e tipos são listas fixas: preenchidas ANTES de qualquer chamada de
  // rede. Se dependessem da API, uma falha de conexão deixaria o formulário
  // vazio e sem explicação — foi exatamente o que acontecia antes.
  preencherMeses();
  preencherTipos(TIPOS_DESASTRE);
  prepararMapa();

  try {
    const estado = await pedir("/");

    // O servidor é a fonte da verdade: se ele conhecer outros tipos (porque
    // alguém mudou src/esquema.py), a lista local é substituída.
    if (estado.tipos_de_desastre && estado.tipos_de_desastre.length) {
      preencherTipos(estado.tipos_de_desastre);
    }

    if (!estado.modelo_carregado) {
      bloquearFormulario(estado.mensagem || "O modelo ainda não foi treinado.");
      return;
    }

    const info = await pedir("/modelo/info");
    $("rodape-modelo").textContent =
      `Modelo treinado em ${formatarData(info.treinado_em)} · `
      + `origem dos dados: ${info.origem_dados} · `
      + `${(info.linhas_de_treino || 0).toLocaleString("pt-BR")} linhas`;
    if (info.aviso) mostrarAviso(info.aviso, false);

    mostrarOddsRatio();
  } catch (erro) {
    const abertoComoArquivo = location.protocol === "file:";
    bloquearFormulario(
      "Não foi possível falar com a API.\n\n"
      + (abertoComoArquivo
        ? "Esta página foi aberta direto do arquivo, e o navegador bloqueia "
          + "esse tipo de acesso.\n\n"
          + "Suba o servidor a partir da raiz do projeto:\n"
          + "    uvicorn backend.app:app --reload\n\n"
          + "e abra http://127.0.0.1:8000/app"
        : "Verifique se o servidor está no ar:\n"
          + "    uvicorn backend.app:app --reload")
    );
  }
}

function bloquearFormulario(mensagem) {
  mostrarAviso(mensagem, true);
  $("botao").disabled = true;
  $("busca").disabled = true;
  $("busca").placeholder = "indisponível — veja o aviso acima";
}

function preencherMeses() {
  const seletor = $("mes");
  const mesAtual = new Date().getMonth();
  MESES.forEach((nome, i) => {
    const opcao = new Option(nome, i + 1, false, i === mesAtual);
    seletor.add(opcao);
  });
}

function preencherTipos(tipos) {
  const seletor = $("tipo");
  const escolhaAtual = seletor.value;

  seletor.innerHTML = "";
  (tipos || []).forEach((tipo) => {
    seletor.add(new Option(formatarTipo(tipo), tipo));
  });

  // Não perde a escolha da pessoa quando a lista é atualizada pela API.
  if (escolhaAtual && tipos.includes(escolhaAtual)) seletor.value = escolhaAtual;
}

// ---------------------------------------------------------------------------
// Busca de município (autocomplete)
// ---------------------------------------------------------------------------

$("busca").addEventListener("input", (evento) => {
  const termo = evento.target.value.trim();
  municipioEscolhido = null;
  $("botao").disabled = true;
  $("municipio-escolhido").classList.add("oculto");

  clearTimeout(temporizadorBusca);
  if (termo.length < 3) {
    $("sugestoes").classList.add("oculto");
    return;
  }
  // Espera a pessoa parar de digitar antes de consultar a API.
  temporizadorBusca = setTimeout(() => buscarMunicipios(termo), 250);
});

async function buscarMunicipios(termo) {
  try {
    const dados = await pedir(`/municipios?busca=${encodeURIComponent(termo)}&limite=8`);
    const lista = $("sugestoes");
    lista.innerHTML = "";

    if (!dados.municipios.length) {
      lista.innerHTML = '<li class="uf">Nenhum município encontrado no Atlas</li>';
      lista.classList.remove("oculto");
      return;
    }

    dados.municipios.forEach((m) => {
      const item = document.createElement("li");
      item.innerHTML = `${m.municipio} <span class="uf">— ${m.uf} · `
                     + `${m.ocorrencias} ocorrência(s)</span>`;
      item.onclick = () => escolherMunicipio(m);
      lista.appendChild(item);
    });
    lista.classList.remove("oculto");
  } catch (erro) {
    /* silencioso: a busca é auxiliar e o erro já aparece no envio */
  }
}

function escolherMunicipio(m) {
  municipioEscolhido = m;
  $("busca").value = m.municipio;
  $("sugestoes").classList.add("oculto");
  $("municipio-escolhido").textContent =
    `${m.municipio} — ${m.uf} (${m.regiao}) · ${m.ocorrencias} ocorrências no Atlas`;
  $("municipio-escolhido").classList.remove("oculto");
  $("botao").disabled = false;
  carregarHistorico(m.codigo_ibge);
}

document.addEventListener("click", (evento) => {
  if (!evento.target.closest(".campo-busca")) {
    $("sugestoes").classList.add("oculto");
  }
});

// ---------------------------------------------------------------------------
// Previsão
// ---------------------------------------------------------------------------

$("formulario").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (!municipioEscolhido) return;

  const tipo = $("tipo").value;
  const mes = Number($("mes").value);
  const ano = new Date().getFullYear();

  $("botao").disabled = true;
  $("botao").textContent = "Calculando...";

  try {
    const previsao = await pedir("/prever/municipio", {
      codigo_ibge: municipioEscolhido.codigo_ibge,
      grupo_desastre: tipo, mes, ano,
    });
    mostrarResultado(previsao);
    await mostrarAno(municipioEscolhido.codigo_ibge, tipo, ano, mes);
  } catch (erro) {
    mostrarAviso(`Não foi possível prever: ${erro.message}`, true);
  } finally {
    $("botao").disabled = false;
    $("botao").textContent = "Prever risco";
  }
});

function mostrarResultado(p) {
  $("resultado").classList.remove("oculto");

  $("selo").textContent = p.nivel_risco;
  $("selo").className = `selo ${p.nivel_risco}`;

  $("resultado-titulo").textContent =
    `${p.municipio} (${p.uf}) — ${formatarTipo(p.grupo_desastre)} em ${MESES[p.mes - 1]}`;
  $("resultado-detalhe").textContent =
    `${EXPLICACAO[p.nivel_risco]} Confiança do modelo: ${porcento(p.confianca)}.`;

  const barras = $("barras");
  barras.innerHTML = "";
  ["baixo", "medio", "alto"].forEach((nivel) => {
    const valor = p.probabilidades[nivel] || 0;
    const linha = document.createElement("div");
    linha.className = "barra-linha";
    linha.innerHTML =
      `<span class="barra-nome">${nivel}</span>
       <div class="barra-trilho">
         <div class="barra-preenchida" style="width:${(valor * 100).toFixed(1)}%;
              background:${CORES[nivel]}"></div>
       </div>
       <span class="barra-valor">${porcento(valor)}</span>`;
    barras.appendChild(linha);
  });

  const tabela = $("tabela-features");
  tabela.innerHTML = "<tr><th>Variável</th><th>Valor</th></tr>";
  Object.entries(p.historico_usado).forEach(([chave, valor]) => {
    const linha = tabela.insertRow();
    linha.insertCell().textContent = ROTULOS[chave] || chave;
    const celula = linha.insertCell();
    celula.className = "numero";
    celula.textContent = formatarValor(chave, valor);
  });

  $("resultado").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function mostrarAno(codigoIbge, tipo, ano, mesEscolhido) {
  const pedidos = MESES.map((_, i) =>
    pedir("/prever/municipio", {
      codigo_ibge: codigoIbge, grupo_desastre: tipo, mes: i + 1, ano,
    }));
  const previsoes = await Promise.all(pedidos);

  const valores = previsoes.map((p) => p.probabilidades.alto || 0);
  const maximo = Math.max(...valores, 0.01);

  const grafico = $("grafico");
  grafico.innerHTML = "";
  valores.forEach((valor, i) => {
    const coluna = document.createElement("div");
    coluna.className = "coluna" + (i + 1 === mesEscolhido ? " destaque" : "");
    coluna.innerHTML =
      `<span class="coluna-valor">${porcento(valor)}</span>
       <div class="coluna-barra" style="height:${(valor / maximo) * 100}%"></div>
       <span class="coluna-mes">${MESES[i].slice(0, 3)}</span>`;
    coluna.title = `${MESES[i]}: ${porcento(valor)} de risco alto`;
    grafico.appendChild(coluna);
  });

  $("secao-ano").classList.remove("oculto");
}

// ---------------------------------------------------------------------------
// Mapa do Brasil
// ---------------------------------------------------------------------------

// A malha tem ~3 MB: é buscada uma vez e reaproveitada em todos os desenhos.
let malhaCache = null;

function prepararMapa() {
  const tipo = $("mapa-tipo");
  TIPOS_DESASTRE.forEach((t) => tipo.add(new Option(formatarTipo(t), t)));
  tipo.value = "INUNDACAO";

  const mes = $("mapa-mes");
  MESES.forEach((nome, i) => mes.add(new Option(nome, i + 1, false, i === 1)));

  $("form-mapa").addEventListener("submit", (evento) => {
    evento.preventDefault();
    desenharMapa(tipo.value, Number(mes.value));
  });
}

async function desenharMapa(tipo, mes) {
  const botao = $("mapa-botao");
  botao.disabled = true;
  botao.textContent = "Desenhando...";
  $("mapa-estado").textContent = malhaCache
    ? "Calculando o risco de cada município..."
    : "Baixando as fronteiras dos municípios (3 MB, só na primeira vez)...";

  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");
    const dados = await pedir(
      `/mapa/brasil?grupo_desastre=${tipo}&mes=${mes}&ano=${new Date().getFullYear()}`
    );

    const porMunicipio = new Map(
      dados.municipios.map((m) => [m.codigo_ibge, m])
    );
    renderizarSvg(malhaCache, porMunicipio);

    $("mapa-estado").textContent =
      `${formatarTipo(tipo)} em ${MESES[mes - 1]} · `
      + `${dados.total.toLocaleString("pt-BR")} municípios com histórico · `
      + `${dados.resumo.alto} em risco alto, ${dados.resumo.medio} em médio.`;

    montarLegenda(dados.resumo);
  } catch (erro) {
    $("mapa-estado").textContent = `Não foi possível montar o mapa: ${erro.message}`;
  } finally {
    botao.disabled = false;
    botao.textContent = "Desenhar mapa";
  }
}

function renderizarSvg(malha, porMunicipio) {
  const svg = $("mapa-svg");
  const LARGURA = 600, ALTURA = 620;

  // Projeção equirretangular: longitude vira x, latitude vira y. Para um país
  // só, a distorção é pequena e não exige biblioteca de projeção.
  let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
  const visitar = (coords, aplicar) => {
    if (typeof coords[0] === "number") aplicar(coords);
    else coords.forEach((c) => visitar(c, aplicar));
  };
  malha.features.forEach((f) => visitar(f.geometry.coordinates, ([lon, lat]) => {
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }));

  const escala = Math.min(LARGURA / (maxLon - minLon), ALTURA / (maxLat - minLat));
  const deslocaX = (LARGURA - (maxLon - minLon) * escala) / 2;
  const deslocaY = (ALTURA - (maxLat - minLat) * escala) / 2;
  const px = (lon) => (lon - minLon) * escala + deslocaX;
  // O y do SVG cresce para baixo; a latitude cresce para cima.
  const py = (lat) => (maxLat - lat) * escala + deslocaY;

  const anelParaPath = (anel) =>
    "M" + anel.map(([lon, lat]) => `${px(lon).toFixed(1)},${py(lat).toFixed(1)}`)
                .join("L") + "Z";

  const partes = [];
  malha.features.forEach((f) => {
    const codigo = f.properties.codigo_ibge;
    const info = porMunicipio.get(codigo);
    const geometria = f.geometry;
    const poligonos = geometria.type === "Polygon"
      ? [geometria.coordinates] : geometria.coordinates;

    const d = poligonos.map((p) => p.map(anelParaPath).join("")).join("");
    if (!d) return;

    if (info) {
      partes.push(
        `<path d="${d}" fill="${info.cor}" data-ibge="${codigo}"></path>`
      );
    } else {
      partes.push(`<path d="${d}" class="sem-dado"></path>`);
    }
  });

  svg.innerHTML = partes.join("");

  // Um único listener no SVG, em vez de 5.570 — a diferença de desempenho
  // é grande o bastante para travar a página se feito do outro jeito.
  svg.onmousemove = (evento) => {
    const alvo = evento.target.closest("path[data-ibge]");
    const dica = $("mapa-dica");
    if (!alvo) { dica.classList.add("oculto"); return; }

    const info = porMunicipio.get(Number(alvo.dataset.ibge));
    dica.innerHTML = `<strong>${info.municipio}</strong> — ${info.uf}<br>`
                   + `risco ${info.nivel_risco}<br>`
                   + `chance de ser grave: ${porcento(info.probabilidade_alto)}`;
    const area = $("mapa-svg").getBoundingClientRect();
    dica.style.left = `${evento.clientX - area.left + 14}px`;
    dica.style.top = `${evento.clientY - area.top + 14}px`;
    dica.classList.remove("oculto");
  };
  svg.onmouseleave = () => $("mapa-dica").classList.add("oculto");
}

function montarLegenda(resumo) {
  const legenda = $("mapa-legenda");
  legenda.innerHTML =
    ["baixo", "medio", "alto"].map((nivel) =>
      `<span><i style="background:${CORES[nivel]}"></i>${nivel}
        (${resumo[nivel].toLocaleString("pt-BR")})</span>`
    ).join("")
    + '<span><i style="background:#dfe4ea"></i>sem histórico deste tipo</span>';
  legenda.classList.remove("oculto");
}

async function mostrarOddsRatio() {
  let dados;
  try {
    dados = await pedir("/modelo/odds-ratio?analise=gravidade");
  } catch (erro) {
    return; // modelo treinado sem a análise; a seção simplesmente não aparece
  }

  // Só entram os efeitos confiáveis e estatisticamente distinguíveis de 1.
  const variaveis = dados.variaveis
    .filter((v) => v.significativo && v.confiavel !== false)
    .slice(0, 10);
  if (!variaveis.length) return;

  // Escala centrada em 1 e simétrica em log: um OR de 4 e um de 0,25 têm o
  // mesmo tamanho de barra, em lados opostos. É a leitura correta, porque
  // dobrar e cortar pela metade são efeitos equivalentes.
  const maiorLog = Math.max(...variaveis.map((v) => Math.abs(Math.log(v.odds_ratio))));

  const caixa = $("odds");
  caixa.innerHTML = "";

  variaveis.forEach((v) => {
    const proporcao = Math.abs(Math.log(v.odds_ratio)) / maiorLog;
    const largura = proporcao * 50; // metade do trilho é 100% da escala
    const aumenta = v.odds_ratio >= 1;
    const posicao = aumenta ? `left:50%; width:${largura}%`
                            : `right:50%; width:${largura}%`;

    const linha = document.createElement("div");
    linha.className = "odds-linha";
    linha.innerHTML =
      `<span class="odds-nome">${nomeVariavel(v.variavel)}</span>
       <div class="odds-trilho">
         <div class="odds-centro"></div>
         <div class="odds-barra ${aumenta ? "aumenta" : "reduz"}" style="${posicao}"></div>
       </div>
       <span class="odds-valor">${v.odds_ratio.toFixed(2).replace(".", ",")}x
         <span class="odds-ic">${v.ic95_inferior.toFixed(2)}–${v.ic95_superior.toFixed(2)}</span>
       </span>`;
    linha.title = `${nomeVariavel(v.variavel)}: multiplica a chance por `
                + `${v.odds_ratio.toFixed(2)} (IC 95%: ${v.ic95_inferior.toFixed(2)} a `
                + `${v.ic95_superior.toFixed(2)})`;
    caixa.appendChild(linha);
  });

  $("odds-rodape").textContent =
    `Regressão logística sobre ${dados.n_amostras.toLocaleString("pt-BR")} `
    + `observações (AUC ${dados.auc.toFixed(3).replace(".", ",")}). `
    + `Variáveis numéricas medidas por desvio-padrão.`;

  $("secao-odds").classList.remove("oculto");
}

function nomeVariavel(chave) {
  if (chave.startsWith("grupo_desastre_")) {
    return "Ser " + formatarTipo(chave.replace("grupo_desastre_", "")).toLowerCase();
  }
  if (chave.startsWith("regiao_")) {
    return "Região " + chave.replace("regiao_", "");
  }
  return ROTULOS[chave] || formatarTipo(chave);
}

async function carregarHistorico(codigoIbge) {
  try {
    const h = await pedir(`/municipios/${codigoIbge}/historico`);

    $("historico-resumo").textContent =
      `${h.total_ocorrencias} ocorrências registradas entre `
      + `${h.periodo.primeiro_ano} e ${h.periodo.ultimo_ano}.`;

    const tabela = $("tabela-historico");
    tabela.innerHTML =
      "<tr><th>Tipo</th><th>Ocorrências</th><th>Mortos</th>"
      + "<th>Afetados</th><th>Último</th></tr>";

    h.por_tipo.forEach((t) => {
      const linha = tabela.insertRow();
      linha.insertCell().textContent = formatarTipo(t.grupo_desastre);
      [t.ocorrencias, t.mortos, t.afetados, t.ultimo_ano].forEach((valor, i) => {
        const celula = linha.insertCell();
        celula.className = "numero";
        // O último ano é um ano, não uma contagem: não leva separador de milhar.
        celula.textContent = i === 3 ? valor : Number(valor).toLocaleString("pt-BR");
      });
    });

    $("secao-historico").classList.remove("oculto");
  } catch (erro) {
    $("secao-historico").classList.add("oculto");
  }
}

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

async function pedir(caminho, corpo = null) {
  const opcoes = corpo
    ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo) }
    : {};
  const resposta = await fetch(API + caminho, opcoes);

  if (!resposta.ok) {
    let detalhe = `erro ${resposta.status}`;
    try {
      const json = await resposta.json();
      if (json.detail) detalhe = typeof json.detail === "string"
        ? json.detail : JSON.stringify(json.detail);
    } catch (e) { /* resposta sem corpo JSON */ }
    throw new Error(detalhe);
  }
  return resposta.json();
}

function mostrarAviso(texto, ehErro) {
  const caixa = $("aviso-modelo");
  caixa.textContent = texto;
  caixa.className = ehErro ? "aviso erro" : "aviso";
}

function formatarTipo(chave) {
  return String(chave).replaceAll("_", " ").toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
}

function porcento(valor) {
  return (valor * 100).toFixed(1).replace(".", ",") + "%";
}

function formatarData(iso) {
  if (!iso) return "data desconhecida";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString("pt-BR");
}

function formatarValor(chave, valor) {
  if (chave === "ja_ocorreu") return valor > 0 ? "sim" : "não";
  if (chave === "meses_desde_ultima_ocorrencia" && valor < 0) return "nunca ocorreu";
  if (chave === "prejuizo_historico_log") {
    // Desfaz o log para mostrar um número que faz sentido para quem lê.
    return "R$ " + Math.round(Math.expm1(valor)).toLocaleString("pt-BR");
  }
  if (chave === "anos_de_historico") return valor.toFixed(1).replace(".", ",");
  return Number(valor).toLocaleString("pt-BR");
}

iniciar();
