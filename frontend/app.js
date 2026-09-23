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
  prepararMapaDoAno();

  // Palcos e abas são de interface pura: não dependem da API e precisam
  // funcionar mesmo com o servidor fora do ar, quando a página vira só um
  // aviso de erro que a pessoa ainda tem de conseguir ler.
  ligarPalcos();
  ligarAbas();
  ligarCamera();
  ligarCamadasDeChuva();
  ligarCamadasDeVento();
  ligarCamadasDeTemperatura();
  ligarCapitais();
  carregarCapitais();

  // O mapa por ano lê o Atlas direto, sem passar pelo modelo. Por isso é
  // carregado aqui, fora da verificação de modelo treinado logo abaixo: se o
  // modelo faltar, a previsão para, mas o histórico continua de pé.
  carregarAnos();

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
    if (info.linhas_de_treino) {
      $("numero-modelo").textContent =
        (info.linhas_de_treino / 1000).toFixed(0) + " mil";
    }
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
  $("consulta-mapa").classList.add("oculto");

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

  // O mesmo formulário serve às duas abas, e a pergunta de cada uma é outra.
  // No Histórico ninguém quer saber do risco de um mês que ainda não chegou:
  // quer ver o que o Atlas já registrou naquela cidade.
  if (mapaAtivo === "ano") {
    await consultarHistorico();
    return;
  }

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

    // O voo é a resposta à pergunta "onde fica isso?", e ela não pode esperar
    // as doze previsões do gráfico do ano. Sai junto com o resto, não depois.
    const voo = prepararEVoar(previsao, tipo, mes);

    // Os demais em paralelo, e não um depois do outro. O gráfico do ano custa
    // doze previsões; enfileirado atrás dele, o mapa da cidade demorava quase
    // um minuto para aparecer — tempo suficiente para quem consultou concluir
    // que ele não existe mais. Cada um revela a sua seção quando termina.
    await Promise.all([
      voo,
      mostrarMapaDaConsulta(previsao),
      mostrarMapaDaCidade(municipioEscolhido.codigo_ibge, tipo, mes),
      mostrarAno(municipioEscolhido.codigo_ibge, tipo, ano, mes),
    ]);
  } catch (erro) {
    mostrarAviso(`Não foi possível prever: ${erro.message}`, true);
  } finally {
    $("botao").disabled = false;
    $("botao").textContent = "Prever risco";
  }
});

/**
 * Consulta por município na aba Histórico.
 *
 * Não passa pelo modelo em momento nenhum: o mapa do ano voa até a cidade e o
 * painel mostra o que o Atlas registrou ali. Enquanto este formulário servia
 * só à Previsão, usá-lo daqui disparava treze chamadas a /prever/municipio e
 * ainda arrastava quem consultava de volta para a outra aba — uma resposta
 * sobre o futuro para uma pergunta sobre o passado.
 */
async function consultarHistorico() {
  const tipo = $("tipo").value;
  const botao = $("botao");

  botao.disabled = true;
  botao.textContent = "Buscando...";

  try {
    // O tipo escolhido aqui é o mesmo filtro do mapa do histórico. Deixar os
    // dois em desacordo pousaria a câmera sobre um mapa pintado por outra
    // pergunta — o mesmo cuidado que `prepararEVoar` toma na Previsão.
    if (!projecaoDoMapa["ano-svg"] || $("ano-tipo").value !== tipo) {
      $("ano-tipo").value = tipo;
      await desenharAno(Number($("ano-escolhido").value), tipo);
    } else if (desenhoDoAno) {
      // Entrar na aba já dispara um desenho. Voar antes de ele terminar não
      // encontraria geometria nenhuma e a câmera ficaria parada.
      await desenhoDoAno;
    }

    await carregarHistorico(municipioEscolhido.codigo_ibge);

    // O seletor de estado passa a mostrar onde a câmera está de fato.
    $("ano-uf").value = ufDoCodigo(municipioEscolhido.codigo_ibge) || "";
    destacarNoMapa("ano", municipioEscolhido.codigo_ibge);
    anunciarCidadeNoAno(municipioEscolhido, tipo);
    await voarAteOMunicipio("ano", municipioEscolhido.codigo_ibge);
  } catch (erro) {
    mostrarAviso(`Não foi possível carregar o histórico: ${erro.message}`, true);
  } finally {
    botao.disabled = false;
    botao.textContent = "Ver histórico";
  }
}

/**
 * Conta, na linha do mapa histórico, o que ele mostra da cidade consultada.
 *
 * Voar até um município cinza sem dizer nada deixaria a dúvida no ar: a
 * consulta falhou, ou não houve ocorrência? A tabela ao lado traz o registro
 * inteiro do município; esta linha fala só do recorte que está desenhado.
 */
function anunciarCidadeNoAno(municipio, tipo) {
  const ano = $("ano-escolhido").value;
  const alvo = $("ano-svg").querySelector(`path[data-ibge="${municipio.codigo_ibge}"]`);
  const semDado = !alvo || alvo.classList.contains("sem-dado");
  const oQue = formatarTipo(tipo).toLowerCase();

  // As duas frases concordam com "ocorrência", e não com o tipo: os nomes dos
  // grupos variam em gênero e número ("estiagem seca", "deslizamento",
  // "chuvas intensas") e nenhuma flexão única serviria para todos.
  $("ano-estado").textContent = semDado
    ? `${municipio.municipio} (${municipio.uf}): nenhuma ocorrência de `
      + `${oQue} registrada em ${ano}. O histórico completo do município `
      + `está ao lado.`
    : `${municipio.municipio} (${municipio.uf}) em destaque: com ocorrência `
      + `de ${oQue} registrada em ${ano}.`;
}

/**
 * Leva o mapa grande até o município consultado.
 *
 * Se o mapa na tela é de outro tipo de desastre ou de outro mês, ele é
 * redesenhado antes do voo: pousar sobre um município pintado com o risco de
 * outra pergunta mostraria uma cor que não responde a nada.
 */
async function prepararEVoar(previsao, tipo, mes) {
  mostrarMapa("mapa");

  const jaDesenhado = Boolean(projecaoDoMapa["mapa-svg"]);
  const precisaRedesenhar = !jaDesenhado
    || $("mapa-tipo").value !== tipo
    || Number($("mapa-mes").value) !== mes;

  let redesenho = Promise.resolve();
  if (precisaRedesenhar) {
    $("mapa-tipo").value = tipo;
    $("mapa-mes").value = String(mes);
    mapaJaDesenhado = true;
    redesenho = desenharMapa(tipo, mes);
  }

  // O primeiro cálculo de um tipo e mês novos leva alguns segundos no
  // servidor. Só que o voo não depende dele: onde fica o município é a malha
  // do IBGE que diz, e ela não muda com a pergunta. A câmera parte na hora, e
  // a cor do risco chega por baixo quando ficar pronta. Esperar o desenho
  // para só então começar a voar transformaria a resposta mais imediata da
  // tela — "é aqui" — na mais demorada.
  //
  // A exceção é o primeiro desenho de todos: antes dele não existe geometria
  // projetada, e não há para onde voar.
  if (!jaDesenhado) await redesenho;

  // O seletor de estado passa a mostrar onde a câmera está de fato.
  $("mapa-uf").value = ufDoCodigo(previsao.codigo_ibge) || "";
  destacarNoMapa("mapa", previsao.codigo_ibge);

  await Promise.all([
    redesenho,
    voarAteOMunicipio("mapa", previsao.codigo_ibge),
  ]);

  // O redesenho refaz todos os caminhos e leva o destaque junto.
  destacarNoMapa("mapa", previsao.codigo_ibge);
}

function mostrarResultado(p) {
  $("painel-vazio").classList.add("oculto");
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

  // O painel rola até o resultado sozinho: numa coluna que já tem o mapa da
  // cidade, o gráfico do ano e o histórico, o resultado novo pode ter nascido
  // fora da vista.
  $("painel").scrollTo({ top: 0, behavior: "smooth" });
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

const UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT",
             "PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"];

// Os dois primeiros dígitos do código IBGE identificam a UF. Guardar esse
// mapa evita uma consulta extra só para filtrar o mapa por estado.
const PREFIXO_UF = {
  11:"RO",12:"AC",13:"AM",14:"RR",15:"PA",16:"AP",17:"TO",21:"MA",22:"PI",
  23:"CE",24:"RN",25:"PB",26:"PE",27:"AL",28:"SE",29:"BA",31:"MG",32:"ES",
  33:"RJ",35:"SP",41:"PR",42:"SC",43:"RS",50:"MS",51:"MT",52:"GO",53:"DF",
};

const ufDoCodigo = (codigo) => PREFIXO_UF[Math.floor(codigo / 100000)];

function prepararMapa() {
  const tipo = $("mapa-tipo");
  TIPOS_DESASTRE.forEach((t) => tipo.add(new Option(formatarTipo(t), t)));
  tipo.value = "INUNDACAO";

  const mes = $("mapa-mes");
  MESES.forEach((nome, i) => mes.add(new Option(nome, i + 1, false, i === 1)));

  // O seletor de estado deixou de recortar o desenho: ele agora aponta para
  // onde a câmera deve voar. O mapa continua sendo o país inteiro, e o estado
  // é um enquadramento dele — assim dá para sair de um estado para outro sem
  // recalcular 5.570 polígonos a cada troca.
  const uf = $("mapa-uf");
  uf.add(new Option("Brasil inteiro", ""));
  UFS.forEach((sigla) => uf.add(new Option(sigla, sigla)));
  uf.addEventListener("change", () => voarAteOEstado("mapa", uf.value));

  $("form-mapa").addEventListener("submit", (evento) => {
    evento.preventDefault();
    desenharMapa(tipo.value, Number(mes.value));
  });
}

/** Enquadra um estado — ou o país inteiro, quando nenhum foi escolhido. */
function voarAteOEstado(prefixo, sigla) {
  const projecao = projecaoDoMapa[`${prefixo}-svg`];
  if (!projecao) return;

  if (!sigla) {
    destacarEstado(`${prefixo}-svg`, null);
    voar(prefixo, null);
    return;
  }
  const caixa = projecao.caixasUf.get(sigla);
  if (caixa) {
    // O destaque vem antes do voo, e não depois: assim o estado já está
    // marcado enquanto a câmera se aproxima, e quem assiste vê para onde ela
    // está indo em vez de descobrir só no pouso.
    destacarEstado(`${prefixo}-svg`, sigla);
    voar(prefixo, caixa);
  }
}

async function desenharMapa(tipo, mes) {
  const botao = $("mapa-botao");
  botao.disabled = true;
  botao.textContent = "Desenhando...";
  // O primeiro cálculo de cada combinação de tipo e mês passa de dez segundos
  // no servidor (depois fica em cache). Sem um sinal de que algo está
  // acontecendo, esse tempo é indistinguível de uma tela travada.
  $("teatro-mapa").classList.add("carregando");
  $("mapa-estado").textContent = malhaCache
    ? "Calculando o risco de cada município..."
    : "Baixando as fronteiras dos municípios (3 MB, só na primeira vez)...";

  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");
    await carregarCapitais();
    const dados = await pedir(
      `/mapa/brasil?grupo_desastre=${tipo}&mes=${mes}&ano=${new Date().getFullYear()}`
    );

    const doMapa = dados.municipios;
    const porMunicipio = new Map(doMapa.map((m) => [m.codigo_ibge, m]));

    // Sempre o país inteiro: o recorte por estado agora é trabalho da câmera.
    renderizarSvg("mapa-svg", "mapa-dica", malhaCache.features, porMunicipio);
    atualizarChuva("mapa");
    atualizarVento("mapa");
    atualizarTemperatura("mapa");
    reenquadrar("mapa");

    const resumo = { baixo: 0, medio: 0, alto: 0 };
    doMapa.forEach((m) => { resumo[m.nivel_risco] += 1; });

    $("mapa-estado").textContent =
      `${formatarTipo(tipo)} em ${MESES[mes - 1]}, no Brasil · `
      + `${doMapa.length.toLocaleString("pt-BR")} municípios com histórico · `
      + `${resumo.alto} em risco alto, ${resumo.medio} em médio.`;

    montarLegenda("mapa-legenda", resumo);
  } catch (erro) {
    $("mapa-estado").textContent = `Não foi possível montar o mapa: ${erro.message}`;
  } finally {
    $("teatro-mapa").classList.remove("carregando");
    botao.disabled = false;
    botao.textContent = "Desenhar";
  }
}

// ---------------------------------------------------------------------------
// Mapa do município consultado
// ---------------------------------------------------------------------------

/**
 * Desenha só o município consultado, ampliado, com a cor do risco previsto.
 *
 * Não custa previsão nenhuma: a cor e a probabilidade já vieram na resposta
 * que preencheu o selo do resultado. O único download é o da malha, e ela é
 * a mesma dos outros mapas — quem já desenhou qualquer um deles não baixa
 * nada aqui.
 *
 * É diferente do mapa "A cidade e a região": lá o enquadramento é o do
 * entorno, e o município consultado é um polígono no meio de dezenas. Aqui
 * ele ocupa a tela inteira, que é o que faz a camada de chuva render alguma
 * coisa na escala da cidade.
 */
async function mostrarMapaDaConsulta(previsao) {
  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");
    await carregarCapitais();

    const feicao = malhaCache.features.find(
      (f) => f.properties.codigo_ibge === previsao.codigo_ibge
    );
    if (!feicao) {
      // Município sem polígono na malha (fusão, criação recente): o resto da
      // página continua, só este mapa não tem o que mostrar.
      $("consulta-mapa").classList.add("oculto");
      return;
    }

    const info = {
      municipio: previsao.municipio,
      uf: previsao.uf,
      nivel_risco: previsao.nivel_risco,
      probabilidade_alto: previsao.probabilidades.alto || 0,
      cor: previsao.cor,
    };

    renderizarSvg("consulta-svg", "consulta-dica", [feicao],
                  new Map([[previsao.codigo_ibge, info]]), previsao.codigo_ibge);

    // O contorno leva a cor do risco, e não o azul-marinho dos outros mapas.
    // Com a chuva ligada, o preenchimento clareia e o município ficaria sem
    // dizer nada — aqui ele é o único polígono da tela, e o risco dele é a
    // resposta inteira. No traço, a cor não some.
    const desenhado = $("consulta-svg").querySelector("path.foco");
    if (desenhado) desenhado.style.stroke = info.cor;

    atualizarChuva("consulta");
    atualizarTemperatura("consulta");

    $("consulta-legenda").innerHTML =
      `<span><i style="background:${info.cor}"></i>risco ${info.nivel_risco}</span>`
      + `<span>${formatarTipo(previsao.grupo_desastre)} em `
      + `${MESES[previsao.mes - 1]}</span>`
      + `<span>chance de ser grave: ${porcento(info.probabilidade_alto)}</span>`;
    $("consulta-legenda").classList.remove("oculto");

    $("consulta-mapa").classList.remove("oculto");
  } catch (erro) {
    $("consulta-mapa").classList.add("oculto");
  }
}

// ---------------------------------------------------------------------------
// Mapa da cidade e da região
// ---------------------------------------------------------------------------

async function mostrarMapaDaCidade(codigoIbge, tipo, mes) {
  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");
    await carregarCapitais();
    const dados = await pedir(
      `/mapa/municipio/${codigoIbge}?grupo_desastre=${tipo}&mes=${mes}`
      + `&ano=${new Date().getFullYear()}`
    );

    const daRegiao = new Set(dados.codigos_da_vizinhanca);
    const feicoes = malhaCache.features.filter(
      (f) => daRegiao.has(f.properties.codigo_ibge)
    );
    if (!feicoes.length) return;

    const porMunicipio = new Map(dados.municipios.map((m) => [m.codigo_ibge, m]));
    renderizarSvg("cidade-svg", "cidade-dica", feicoes, porMunicipio, codigoIbge);
    atualizarChuva("cidade");
    atualizarTemperatura("cidade");

    const resumo = { baixo: 0, medio: 0, alto: 0 };
    dados.municipios.forEach((m) => { resumo[m.nivel_risco] += 1; });
    montarLegenda("cidade-legenda", resumo);

    $("cidade-setores").innerHTML = textoDosSetores(dados);
    $("secao-cidade").classList.remove("oculto");
  } catch (erro) {
    $("secao-cidade").classList.add("oculto");
  }
}

function textoDosSetores(dados) {
  const s = dados.setores_afetados || {};
  if (!s.disponivel) {
    return "O Atlas não registrou quais partes da cidade foram atingidas "
         + "nas ocorrências deste tipo.";
  }
  return `<strong>${s.setores_distintos} setores censitários</strong> desta `
       + `cidade já foram atingidos por ${formatarTipo(dados.grupo_desastre)}, `
       + `em ${s.ocorrencias_com_setor} das ${s.ocorrencias_do_tipo} ocorrências `
       + `registradas. O IBGE não publica o desenho desses setores, então o `
       + `número aparece sem o mapa de bairros.`;
}

// ---------------------------------------------------------------------------
// Camada de chuva medida
// ---------------------------------------------------------------------------
// Desenha, sobre o mapa, quanto choveu de fato — medido pelas estações
// automáticas do INMET.
//
// O ponto delicado é de onde vem o número. O arquivo que alimenta o modelo
// tem uma linha por município, mas em 92% delas a chuva foi medida em outro
// município: só 8% do país tem estação própria. Pintar município a município
// com esses valores desenharia uma precisão que não existe.
//
// Por isso a camada trabalha com os PONTOS: interpola entre as ~600 estações
// reais (é o que o Windy faz entre os pontos da grade dele) e desenha os
// marcadores por cima. Quem olha vê a mancha e vê de onde ela veio.

const GRADE_CHUVA = 120;  // resolução do cálculo, antes de o navegador suavizar
const RAIO_CHUVA = 3.2;   // graus: além disso, nenhuma estação influencia
const POTENCIA_IDW = 2.4; // quanto o peso cai com a distância

// Cada mapa e o que ele pede à API.
const MAPAS_COM_CHUVA = {
  consulta: { svg: "consulta-svg", periodo: () => ({ mes: Number($("mes").value) }) },
  mapa: { svg: "mapa-svg", periodo: () => ({ mes: Number($("mapa-mes").value) }) },
  cidade: { svg: "cidade-svg", periodo: () => ({ mes: Number($("mes").value) }) },
  ano: {
    svg: "ano-svg",
    // No mapa por ano faz sentido o acumulado do ano inteiro escolhido.
    periodo: () => ({ ano: Number($("ano-escolhido").value) }),
  },
};

function ligarCamadasDeChuva() {
  for (const prefixo of Object.keys(MAPAS_COM_CHUVA)) {
    const caixa = $(`${prefixo}-chuva`);
    if (caixa) caixa.addEventListener("change", () => atualizarChuva(prefixo));
  }
}

/** Liga, desliga ou redesenha a camada de chuva de um mapa. */
async function atualizarChuva(prefixo) {
  const caixa = $(`${prefixo}-chuva`);
  const tela = $(`${prefixo}-chuva-canvas`);
  const area = tela ? tela.closest(".mapa-area") : null;
  const rodape = $(`${prefixo}-chuva-nota`);
  if (!caixa || !tela || !area) return;

  const contexto = tela.getContext("2d");
  contexto.clearRect(0, 0, tela.width, tela.height);

  if (!caixa.checked) {
    // Sem a camada, o mapa volta a ser o dono da cor. A legenda sai junto:
    // uma escala de chuva embaixo de um mapa sem chuva explica o que não
    // está desenhado.
    area.classList.remove("com-chuva");
    rodape.classList.add("oculto");
    $(`${prefixo}-chuva-legenda`).classList.add("oculto");
    return;
  }

  const projecao = projecaoDoMapa[MAPAS_COM_CHUVA[prefixo].svg];
  if (!projecao) {
    rodape.textContent = "Desenhe o mapa primeiro para sobrepor a chuva.";
    rodape.classList.remove("oculto");
    return;
  }

  rodape.textContent = "Buscando as medições do INMET...";
  rodape.classList.remove("oculto");

  try {
    const { ano, mes } = MAPAS_COM_CHUVA[prefixo].periodo();
    const parametros = new URLSearchParams();
    if (ano) parametros.set("ano", ano);
    if (mes) parametros.set("mes", mes);

    const dados = await pedir(`/clima/chuva?${parametros}`);

    // Com a chuva por cima, o mapa embaixo vira referência geográfica: as
    // duas escalas de cor disputando a mesma área não se leem.
    area.classList.add("com-chuva");
    pintarChuva(tela, projecao, dados);
    montarLegendaDeChuva(`${prefixo}-chuva-legenda`, dados);

    rodape.textContent =
      `Chuva medida em ${dados.periodo}, por ${dados.total_estacoes} estações `
      + `automáticas do INMET · média ${dados.chuva_media_mm} mm, máxima `
      + `${dados.chuva_maxima_mm} mm. Cada ponto é uma estação; entre elas o `
      + `valor é interpolado, e a mancha para na fronteira do que está `
      + `desenhado. Quanto mais forte a cor, mais choveu.`;
  } catch (erro) {
    caixa.checked = false;
    area.classList.remove("com-chuva");
    $(`${prefixo}-chuva-legenda`).classList.add("oculto");
    rodape.textContent = `Sem camada de chuva: ${erro.message}`;
  }
}

// ---------------------------------------------------------------------------
// Camada de vento
// ---------------------------------------------------------------------------
// Para onde o vento predominante sopra em cada mês, medido pelas estações do
// INMET. O desenho fica em vento.js; aqui ficam o interruptor, a busca na API
// e a legenda.
//
// Só os três mapas que escolhem um MÊS têm a camada. O mapa do histórico
// escolhe um ANO, e um vento anual não existe: a direção predominante de
// janeiro e a de julho podem ser opostas, e a média das duas não descreve
// nenhum dos dois.

const MAPAS_COM_VENTO = {
  consulta: { svg: "consulta-svg", mes: () => Number($("mes").value) },
  mapa: { svg: "mapa-svg", mes: () => Number($("mapa-mes").value) },
  cidade: { svg: "cidade-svg", mes: () => Number($("mes").value) },
};

// Uma camada por mapa, criada na primeira vez que o mapa pede vento.
const camadasDeVento = {};

function ligarCamadasDeVento() {
  for (const prefixo of Object.keys(MAPAS_COM_VENTO)) {
    const caixa = $(`${prefixo}-vento`);
    if (caixa) caixa.addEventListener("change", () => atualizarVento(prefixo));
  }
}

/** Liga, desliga ou redesenha a camada de vento de um mapa. */
async function atualizarVento(prefixo) {
  const caixa = $(`${prefixo}-vento`);
  const tela = $(`${prefixo}-vento-canvas`);
  const area = tela ? tela.closest(".mapa-area") : null;
  const rodape = $(`${prefixo}-vento-nota`);
  if (!caixa || !tela || !area) return;

  const camada = camadasDeVento[prefixo]
    || (camadasDeVento[prefixo] = Vento.camada(tela));

  if (!caixa.checked) {
    // Parar é obrigatório, e não zelo: o laço de animação continuaria rodando
    // atrás de um canvas invisível, gastando bateria para desenhar o que
    // ninguém vê.
    camada.limpar();
    area.classList.remove("com-vento");
    rodape.classList.add("oculto");
    $(`${prefixo}-vento-legenda`).classList.add("oculto");
    return;
  }

  const projecao = projecaoDoMapa[MAPAS_COM_VENTO[prefixo].svg];
  if (!projecao) {
    rodape.textContent = "Desenhe o mapa primeiro para sobrepor o vento.";
    rodape.classList.remove("oculto");
    return;
  }

  rodape.textContent = "Buscando o vento medido pelo INMET...";
  rodape.classList.remove("oculto");

  try {
    const mes = MAPAS_COM_VENTO[prefixo].mes();
    const dados = await pedir(`/clima/vento?mes=${mes}`);

    // O interruptor pode ter sido desligado enquanto a resposta vinha.
    if (!caixa.checked) return;

    area.classList.add("com-vento");
    // O enquadramento vai como função, e não como valor: a câmera muda a cada
    // voo, e a camada precisa do retângulo de agora, não do de quando a
    // camada foi ligada.
    camada.desenhar(projecao, dados, mascaraDoMapa(projecao),
                    () => enquadramentoDoVento(prefixo));
    montarLegendaDeVento(`${prefixo}-vento-legenda`, dados);

    rodape.textContent =
      `Vento predominante em ${dados.periodo}, medido por `
      + `${dados.total_estacoes} estações automáticas do INMET ao longo de `
      + `${dados.anos_medidos} anos · média ${dados.velocidade_media_ms} m/s, `
      + `máxima ${dados.velocidade_maxima_ms} m/s. Cada risco segue o rumo do `
      + `ar; a cor é a velocidade. Entre as estações o valor é interpolado, e `
      + `a animação corre mais rápido que o vento real, para o rumo aparecer.`;
  } catch (erro) {
    caixa.checked = false;
    camada.limpar();
    area.classList.remove("com-vento");
    $(`${prefixo}-vento-legenda`).classList.add("oculto");
    rodape.textContent = `Sem camada de vento: ${erro.message}`;
  }
}

/**
 * Onde o mapa está na tela: a escala e o deslocamento da câmera.
 *
 * Leva um ponto do desenho a um pixel de tela por
 * `deslocamento + escala * ponto` — exatamente a transformação que o
 * `aplicarCamera` publica no CSS, e é de propósito que seja a mesma conta: a
 * camada de vento precisa pousar em cima do mapa, e não ao lado dele.
 *
 * O canvas do vento fica FORA da câmera justamente para receber isto: dentro
 * dela, ele seria ampliado como bitmap e borraria. Fora, ele tem o tamanho da
 * tela e é o desenho que se move.
 *
 * Devolve `null` para os mapas do painel, que não têm câmera nenhuma — lá o
 * próprio vento.js calcula o ajuste do SVG à caixa.
 */
function enquadramentoDoVento(prefixo) {
  const estado = cameras[prefixo];
  const teatro = $(`teatro-${prefixo}`);
  if (!estado || !teatro || !estado.escala) return null;

  return {
    escala: estado.escala,
    deslocaX: teatro.clientWidth / 2 - estado.escala * estado.x,
    deslocaY: teatro.clientHeight / 2 - estado.escala * estado.y,
    largura: teatro.clientWidth,
    altura: teatro.clientHeight,
  };
}

/**
 * Suspende ou retoma todas as camadas de vento de uma vez.
 *
 * As três vivem no palco dos mapas e na aba da previsão. Fora dali — na aba
 * do histórico, na abertura, na despedida — elas continuariam animando atrás
 * de uma tela que ninguém está vendo, gastando bateria para desenhar o
 * invisível. O campo fica guardado: voltar é imediato, sem refazer a
 * interpolação nem buscar de novo na API.
 */
function ventosEmCena(emCena) {
  for (const camada of Object.values(camadasDeVento)) {
    if (emCena) camada.seguir(); else camada.pausar();
  }
}

function montarLegendaDeVento(idLegenda, dados) {
  const escala = dados.escala;
  const topo = escala[escala.length - 1].de || 1;
  const posicao = (valor) => ((valor / topo) * 100).toFixed(1);

  const degrade = escala.map((f) => `${f.cor} ${posicao(f.de)}%`).join(", ");

  const marcas = escala.slice(1).map((f, i) => {
    const numero = f.de.toLocaleString("pt-BR");
    const rotulo = i === escala.length - 2 ? `${numero}+` : numero;
    return `<span style="left:${posicao(f.de)}%">${rotulo}</span>`;
  }).join("");

  const legenda = $(idLegenda);
  legenda.innerHTML =
    `<span class="legenda-titulo">vento predominante (${dados.unidade})</span>
     <div class="escala-chuva">
       <div class="escala-barra" style="background:linear-gradient(90deg,${degrade})"></div>
       <div class="escala-marcas">${marcas}</div>
     </div>
     <span class="legenda-estacao"><i></i>constância média ${
       dados.constancia_media.toLocaleString("pt-BR")
     } — 1 é vento sempre no mesmo rumo</span>`;
  legenda.classList.remove("oculto");
  esconderMarcasQueColidem(legenda);
}


// ---------------------------------------------------------------------------
// Camada de temperatura — o mapa de calor
// ---------------------------------------------------------------------------
// A temperatura do ar medida pelas ~600 estações automáticas do INMET,
// interpolada num campo contínuo, como o Windy faz com a dele.
//
// Por que ela é desenhada diferente da chuva
// ------------------------------------------
// A chuva é uma INTENSIDADE: existe "não choveu", e onde chove pouco a camada
// se apaga de propósito para o mapa reaparecer. Temperatura não tem zero nem
// ausência — todo ponto do país tem uma, sempre —, então a camada é CHEIA e
// de opacidade constante. Apagá-la onde faz frio seria dizer que ali falta
// dado, e não falta.
//
// É por isso que ela também fica na camada de baixo: é o fundo sobre o qual a
// chuva e o vento continuam legíveis.
//
// O que este mapa NÃO diz
// -----------------------
// Ele não corrige a altitude. O ar esfria ~6,5 °C a cada 1.000 m, e a
// interpolação não sabe onde estão as serras: entre uma estação de praia e
// uma de montanha, ela desenha a transição como se o relevo fosse uma rampa.
// Perto de cada estação o número é o medido; longe de todas, é estimativa. O
// rodapé da camada diz isso, e os pontos das estações mostram onde é qual.
// Corrigir de verdade exigiria um modelo de elevação do terreno, que é o
// próximo passo anotado em dados/README.md.

const GRADE_TEMPERATURA = 160;   // mais fina que a da chuva — ver abaixo
const RAIO_TEMPERATURA = 6.5;    // graus: o alcance de uma estação
const POTENCIA_IDW_TEMPERATURA = 2.0;
// Distância, em unidades do desenho, abaixo da qual a estação para de ganhar
// peso. Sem esse piso o peso vai a infinito em cima da estação e cada uma
// vira um ponto de cor chapada — o "olho de boi" clássico da interpolação.
const SUAVIZACAO_TEMPERATURA = 2.5;

// Cada mapa e o que ele pede à API.
//
// Os três mapas de previsão pedem só o MÊS, sem ano: eles estimam o risco de
// um mês que ainda não chegou, e a temperatura de um mês futuro não existe.
// Sem `ano`, a API responde com o mês típico de todos os anos medidos — que é
// a mesma pergunta que o modelo de risco responde, pelo outro lado.
//
// O mapa do histórico escolhe um ANO, e aí a pergunta é outra: a temperatura
// média daquele ano, de fato. Diferente do vento, isso significa alguma coisa
// — média de médias continua sendo média, enquanto a direção predominante de
// um ano inteiro não descreve mês nenhum.
const MAPAS_COM_TEMPERATURA = {
  consulta: { svg: "consulta-svg", periodo: () => ({ mes: Number($("mes").value) }) },
  mapa: { svg: "mapa-svg", periodo: () => ({ mes: Number($("mapa-mes").value) }) },
  cidade: { svg: "cidade-svg", periodo: () => ({ mes: Number($("mes").value) }) },
  ano: {
    svg: "ano-svg",
    periodo: () => ({ ano: Number($("ano-escolhido").value) }),
  },
};

// A última resposta da API, por mapa. Guardada para o redesenho do zoom não
// precisar pedir tudo de novo: o campo é o mesmo, só o tamanho dos marcadores
// muda, e refazer a busca a cada pouso da câmera seria pedir 550 estações
// para desenhar exatamente os mesmos números.
const dadosDoCalor = {};

// Um relógio por mapa, para o redesenho do zoom. Ver `agendarRedesenhoDoCalor`.
const relogioDoCalor = {};

function ligarCamadasDeTemperatura() {
  for (const prefixo of Object.keys(MAPAS_COM_TEMPERATURA)) {
    const caixa = $(`${prefixo}-temperatura`);
    if (caixa) caixa.addEventListener("change", () => atualizarTemperatura(prefixo));
  }
}

/**
 * Redesenha o mapa de calor depois que a câmera pousa.
 *
 * O canvas vive DENTRO da câmera, então ele é ampliado junto com o mapa — um
 * bitmap de 1000x820 esticado. Para o campo isso não incomoda: temperatura é
 * lisa, e ampliar uma mancha lisa continua dando uma mancha lisa. Para os
 * marcadores das estações, incomoda muito: um ponto de 1,6 px ampliado 36
 * vezes vira um borrão de 58 px atravessado na tela.
 *
 * A saída é desenhar o marcador com o tamanho dividido pela ampliação, e é
 * por isso que o desenho precisa refazer-se quando a câmera muda — o que esta
 * função agenda.
 *
 * O adiamento não é economia, é necessidade: `aplicarCamera` roda a cada
 * quadro do voo, e repintar 25.600 células sessenta vezes por segundo
 * travaria a animação. Cada quadro reinicia o relógio, então o redesenho sai
 * uma vez só, quando a câmera já parou.
 */
function agendarRedesenhoDoCalor(prefixo) {
  const caixa = $(`${prefixo}-temperatura`);
  const dados = dadosDoCalor[prefixo];
  if (!caixa || !caixa.checked || !dados) return;

  clearTimeout(relogioDoCalor[prefixo]);
  relogioDoCalor[prefixo] = setTimeout(() => {
    const tela = $(`${prefixo}-temperatura-canvas`);
    const projecao = projecaoDoMapa[MAPAS_COM_TEMPERATURA[prefixo].svg];
    if (tela && projecao && caixa.checked) {
      pintarTemperatura(tela, projecao, dados, cameras[prefixo]?.escala || 1);
    }
  }, 140);
}

/** Liga, desliga ou redesenha o mapa de calor de um mapa. */
async function atualizarTemperatura(prefixo) {
  const caixa = $(`${prefixo}-temperatura`);
  const tela = $(`${prefixo}-temperatura-canvas`);
  const area = tela ? tela.closest(".mapa-area") : null;
  const rodape = $(`${prefixo}-temperatura-nota`);
  if (!caixa || !tela || !area) return;

  const contexto = tela.getContext("2d");
  contexto.clearRect(0, 0, tela.width, tela.height);

  if (!caixa.checked) {
    area.classList.remove("com-temperatura");
    rodape.classList.add("oculto");
    $(`${prefixo}-temperatura-legenda`).classList.add("oculto");
    // Sem o descarte, um redesenho agendado antes de desligar ainda acharia
    // dado para pintar e acenderia a camada de volta sozinha.
    delete dadosDoCalor[prefixo];
    clearTimeout(relogioDoCalor[prefixo]);
    return;
  }

  const projecao = projecaoDoMapa[MAPAS_COM_TEMPERATURA[prefixo].svg];
  if (!projecao) {
    rodape.textContent = "Desenhe o mapa primeiro para sobrepor a temperatura.";
    rodape.classList.remove("oculto");
    return;
  }

  rodape.textContent = "Buscando as medições do INMET...";
  rodape.classList.remove("oculto");

  try {
    const { ano, mes } = MAPAS_COM_TEMPERATURA[prefixo].periodo();
    const parametros = new URLSearchParams();
    if (ano) parametros.set("ano", ano);
    if (mes) parametros.set("mes", mes);

    const dados = await pedir(`/clima/temperatura?${parametros}`);

    // O interruptor pode ter sido desligado enquanto a resposta vinha.
    if (!caixa.checked) return;

    area.classList.add("com-temperatura");
    dadosDoCalor[prefixo] = dados;
    pintarTemperatura(tela, projecao, dados, cameras[prefixo]?.escala || 1);
    montarLegendaDeTemperatura(`${prefixo}-temperatura-legenda`, dados);

    rodape.textContent =
      `Temperatura do ar (${dados.descricao_grandeza}) em ${dados.periodo}, `
      + `medida por ${dados.total_estacoes} estações automáticas do INMET · `
      + `média ${dados.temperatura_media_c} °C, de `
      + `${dados.mais_fria.temperatura_c} °C em ${dados.mais_fria.estacao}/`
      + `${dados.mais_fria.uf} a ${dados.mais_quente.temperatura_c} °C em `
      + `${dados.mais_quente.estacao}/${dados.mais_quente.uf}. Cada ponto é `
      + `uma estação; entre elas o valor é interpolado e não corrige a `
      + `altitude — o ar esfria cerca de 6,5 °C a cada 1.000 m, então serra `
      + `entre estações de planície aparece mais quente do que é.`;
  } catch (erro) {
    caixa.checked = false;
    area.classList.remove("com-temperatura");
    $(`${prefixo}-temperatura-legenda`).classList.add("oculto");
    rodape.textContent = `Sem mapa de calor: ${erro.message}`;
  }
}

/**
 * Índice espacial das estações, em caixas do tamanho do raio de busca.
 *
 * É o que torna a grade fina viável. A camada de chuva compara cada célula
 * com TODAS as estações: 120×120 células × 600 estações são 8,6 milhões de
 * distâncias, e quase todas resultam em "longe demais, ignora".
 *
 * Com as estações distribuídas em caixas de um raio de lado, cada célula só
 * precisa olhar as 9 caixas ao redor da sua — e aí só sobram as estações que
 * têm mesmo chance de influenciar. O custo deixa de depender do total de
 * estações e passa a depender da densidade local, que no Brasil é de poucas
 * dezenas por caixa. É o mesmo truque que qualquer motor de partículas usa
 * para detectar colisão, e é por isso que aqui cabe uma grade de 160×160
 * gastando menos que a de 120×120 da chuva.
 */
function indexarPorProximidade(pontos, raio) {
  const lado = Math.max(raio, 1);
  const caixas = new Map();
  // A lista das 9 caixas vizinhas, guardada por caixa. Sem isto o índice não
  // vale a pena, e a medição foi clara: juntar as 9 listas a cada célula
  // aloca um array por célula — 25.600 arrays por desenho —, e o custo de
  // alocar anula exatamente o que se economizou em distâncias. Medido, o
  // índice sem esta memória empatava com a varredura burra.
  //
  // Com ela, as milhares de células que caem na MESMA caixa reaproveitam a
  // mesma lista, e o índice passa a ganhar de verdade: cerca de metade do
  // tempo da varredura completa, no mapa do Brasil inteiro.
  const vizinhancas = new Map();

  for (const ponto of pontos) {
    const cx = Math.floor(ponto.x / lado);
    const cy = Math.floor(ponto.y / lado);
    const chave = `${cx}:${cy}`;
    const caixa = caixas.get(chave);
    if (caixa) caixa.push(ponto); else caixas.set(chave, [ponto]);
  }

  return {
    lado,
    /** As estações das 9 caixas em volta de (x, y). */
    vizinhas(x, y) {
      const cx = Math.floor(x / lado);
      const cy = Math.floor(y / lado);
      const chave = `${cx}:${cy}`;

      const guardada = vizinhancas.get(chave);
      if (guardada) return guardada;

      const perto = [];
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const caixa = caixas.get(`${cx + dx}:${cy + dy}`);
          if (caixa) perto.push(...caixa);
        }
      }
      vizinhancas.set(chave, perto);
      return perto;
    },
  };
}

/**
 * Interpola a temperatura entre as estações e pinta o mapa de calor.
 *
 * A interpolação é IDW com duas correções, e as duas existem para matar
 * artefatos que aparecem no desenho e não nos números:
 *
 * 1. **Piso de distância** (`SUAVIZACAO_TEMPERATURA`) — sem ele, o peso vai a
 *    infinito em cima de cada estação, e cada uma vira uma bolha de cor
 *    chapada com anel em volta: o "olho de boi". Com o piso, o valor da
 *    estação continua mandando ali perto, mas sem o degrau.
 *
 * 2. **Corte suave** (a gaussiana) — a chuva usa raio com corte seco, e o
 *    limite do alcance vira uma circunferência visível no mapa. Num campo
 *    cheio como o da temperatura isso seria gritante, porque não há célula
 *    transparente para disfarçar. A gaussiana leva o peso a praticamente zero
 *    na borda do raio, então o alcance acaba sem deixar marca.
 */
function pintarTemperatura(tela, projecao, dados, escalaDaCamera = 1) {
  const pontos = dados.estacoes.map((e) => ({
    x: projecao.px(e.lon), y: projecao.py(e.lat), valor: e.temperatura_c,
  }));
  if (!pontos.length) return;

  const rampa = rampaDeCores(dados.escala);

  const passoX = projecao.largura / GRADE_TEMPERATURA;
  const passoY = projecao.altura / GRADE_TEMPERATURA;
  // O raio vale em graus; converte para as unidades do desenho usando a
  // própria projeção, para valer igual num mapa do país e num de estado.
  const raio = Math.abs(projecao.px(RAIO_TEMPERATURA) - projecao.px(0));
  const raio2 = raio * raio;
  const suavizacao2 = SUAVIZACAO_TEMPERATURA * SUAVIZACAO_TEMPERATURA;
  const expoente = POTENCIA_IDW_TEMPERATURA / 2;

  const indice = indexarPorProximidade(pontos, raio);

  const grade = document.createElement("canvas");
  grade.width = GRADE_TEMPERATURA;
  grade.height = GRADE_TEMPERATURA;
  const pincel = grade.getContext("2d");
  const imagem = pincel.createImageData(GRADE_TEMPERATURA, GRADE_TEMPERATURA);

  for (let linha = 0; linha < GRADE_TEMPERATURA; linha++) {
    const y = (linha + 0.5) * passoY;

    for (let coluna = 0; coluna < GRADE_TEMPERATURA; coluna++) {
      const x = (coluna + 0.5) * passoX;

      let soma = 0, pesos = 0, maisPerto = Infinity;
      for (const ponto of indice.vizinhas(x, y)) {
        const dx = ponto.x - x, dy = ponto.y - y;
        const distancia2 = dx * dx + dy * dy;
        if (distancia2 > raio2) continue;
        if (distancia2 < maisPerto) maisPerto = distancia2;

        const queda = Math.exp(-3 * (distancia2 / raio2));
        const peso = queda / Math.pow(distancia2 + suavizacao2, expoente);
        soma += ponto.valor * peso;
        pesos += peso;
      }

      const posicao = (linha * GRADE_TEMPERATURA + coluna) * 4;
      if (!pesos) continue;  // longe de tudo: fica transparente

      const cor = corNaRampa(soma / pesos, rampa);

      // Opacidade constante, ao contrário da chuva. A única coisa que a
      // apaga é a borda da área coberta: sem esse desvanecer, o limite do
      // alcance das estações viraria uma silhueta dura, e borda dura parece
      // fronteira de dado.
      const proximidade = 1 - Math.min(Math.sqrt(maisPerto) / raio, 1);
      const opacidade = 0.86 * Math.min(proximidade * 3, 1);

      imagem.data[posicao] = cor[0];
      imagem.data[posicao + 1] = cor[1];
      imagem.data[posicao + 2] = cor[2];
      imagem.data[posicao + 3] = Math.round(255 * opacidade);
    }
  }

  pincel.putImageData(imagem, 0, 0);

  const contexto = tela.getContext("2d");
  contexto.clearRect(0, 0, tela.width, tela.height);
  contexto.imageSmoothingEnabled = true;
  contexto.imageSmoothingQuality = "high";

  contexto.save();
  // O mesmo recorte da chuva, pelo mesmo motivo: sem ele a camada afirma
  // temperatura no mar e nos estados que ficaram fora do desenho.
  const mascara = mascaraDoMapa(projecao);
  if (mascara) contexto.clip(mascara);
  contexto.drawImage(grade, 0, 0, tela.width, tela.height);

  // O marcador é desenhado no tamanho dividido pela ampliação da câmera, para
  // ocupar sempre o mesmo espaço NA TELA. Sem isso, o ponto de 1,6 px do mapa
  // do Brasil vira um borrão de 58 px quando a câmera fecha num município a
  // 36x — foi o pior defeito visual desta camada.
  //
  // Dividir tem um limite, e ele é honesto: passado um certo zoom o marcador
  // fica menor que um pixel do bitmap e simplesmente desaparece, em vez de
  // virar mancha. É o comportamento certo para o que se está vendo ali — a
  // essa altura a tela mostra um município, e a estação mais próxima quase
  // sempre está fora do quadro.
  desenharEstacoes(contexto, pontos, 0.62 / Math.max(escalaDaCamera, 1));
  contexto.restore();
}

/**
 * Legenda do mapa de calor.
 *
 * Igual à da chuva na aparência, mas com uma diferença que importa: a escala
 * da chuva começa no zero, e a da temperatura não. Posicionar as marcas por
 * `valor / topo` colocaria os 5 °C a um oitavo da barra, quando eles são o
 * começo dela — a legenda mentiria sobre a própria escala que explica.
 */
function montarLegendaDeTemperatura(idLegenda, dados) {
  const escala = dados.escala;
  const base = escala[0].de;
  const topo = escala[escala.length - 1].de;
  const vao = (topo - base) || 1;
  const posicao = (valor) => (((valor - base) / vao) * 100).toFixed(1);

  const degrade = escala.map((f) => `${f.cor} ${posicao(f.de)}%`).join(", ");

  // A primeira marca é o começo da barra e dispensa número; a última leva "+"
  // porque a faixa não tem fim.
  const marcas = escala.slice(1).map((f, i) => {
    const numero = f.de.toLocaleString("pt-BR");
    const rotulo = i === escala.length - 2 ? `${numero}+` : numero;
    return `<span style="left:${posicao(f.de)}%">${rotulo}</span>`;
  }).join("");

  const legenda = $(idLegenda);
  legenda.innerHTML =
    `<span class="legenda-titulo">temperatura do ar (${dados.unidade})</span>
     <div class="escala-chuva">
       <div class="escala-barra" style="background:linear-gradient(90deg,${degrade})"></div>
       <div class="escala-marcas">${marcas}</div>
     </div>
     <span class="legenda-estacao"><i></i>estação do INMET</span>`;
  legenda.classList.remove("oculto");
  esconderMarcasQueColidem(legenda);

  observadorDaLegenda.observe(legenda);
}


/**
 * Interpola a chuva entre as estações e pinta no canvas.
 *
 * O cálculo roda numa grade pequena (120×120) e o resultado é ampliado pelo
 * navegador, que suaviza de graça. Calcular direto nos 640×640 pixels seriam
 * 400 mil células × 600 estações — a página congelaria. Assim são 14 mil
 * células, e o degradê fica igual.
 */
function pintarChuva(tela, projecao, dados) {
  const pontos = dados.estacoes.map((e) => ({
    x: projecao.px(e.lon), y: projecao.py(e.lat), valor: e.chuva_mm,
  }));

  const rampa = rampaDeCores(dados.escala);
  const topo = rampa[rampa.length - 1].valor || 1;

  const passoX = projecao.largura / GRADE_CHUVA;
  const passoY = projecao.altura / GRADE_CHUVA;
  // O raio vale em graus; converte para as unidades do desenho usando a
  // própria projeção, para valer igual num mapa do país e num de estado.
  const raio = Math.abs(projecao.px(RAIO_CHUVA) - projecao.px(0));
  const raio2 = raio * raio;

  const grade = document.createElement("canvas");
  grade.width = GRADE_CHUVA;
  grade.height = GRADE_CHUVA;
  const pincel = grade.getContext("2d");
  const imagem = pincel.createImageData(GRADE_CHUVA, GRADE_CHUVA);

  for (let linha = 0; linha < GRADE_CHUVA; linha++) {
    for (let coluna = 0; coluna < GRADE_CHUVA; coluna++) {
      const x = (coluna + 0.5) * passoX;
      const y = (linha + 0.5) * passoY;

      let soma = 0, pesos = 0, maisPerto = Infinity;
      for (const ponto of pontos) {
        const dx = ponto.x - x, dy = ponto.y - y;
        const distancia2 = dx * dx + dy * dy;
        if (distancia2 > raio2) continue;
        if (distancia2 < maisPerto) maisPerto = distancia2;
        // Distância zero (a célula cai em cima da estação) daria divisão por
        // zero; o piso mantém o valor da própria estação.
        const peso = 1 / Math.pow(Math.max(distancia2, 1), POTENCIA_IDW / 2);
        soma += ponto.valor * peso;
        pesos += peso;
      }

      const posicao = (linha * GRADE_CHUVA + coluna) * 4;
      if (!pesos) continue;  // longe de tudo: fica transparente

      const milimetros = soma / pesos;
      const cor = corNaRampa(milimetros, rampa);

      // Duas coisas apagam a cor, por motivos diferentes.
      //
      // A primeira é a própria chuva: onde choveu pouco a camada quase some e
      // deixa o mapa aparecer. Antes toda célula vinha com a mesma opacidade,
      // e o "quase não choveu" cobria o mapa com a mesma força do "choveu
      // 400 mm" — o olho lia área coberta, e não intensidade.
      //
      // A segunda é a borda da área coberta: some suavemente, em vez de
      // cortar reto numa circunferência, porque aresta dura pareceria
      // fronteira de dado, e não é.
      const intensidade = Math.min(milimetros / topo, 1);
      const proximidade = 1 - Math.min(Math.sqrt(maisPerto) / raio, 1);
      const opacidade = (0.38 + 0.58 * Math.sqrt(intensidade))
                      * Math.min(proximidade * 2.4, 1);

      imagem.data[posicao] = cor[0];
      imagem.data[posicao + 1] = cor[1];
      imagem.data[posicao + 2] = cor[2];
      imagem.data[posicao + 3] = Math.round(255 * opacidade);
    }
  }

  pincel.putImageData(imagem, 0, 0);

  const contexto = tela.getContext("2d");
  contexto.clearRect(0, 0, tela.width, tela.height);
  contexto.imageSmoothingEnabled = true;
  contexto.imageSmoothingQuality = "high";

  contexto.save();
  // Recortada no contorno do próprio mapa, a mancha para de vazar para o mar
  // e para fora do estado escolhido. Sem isso a camada pintava chuva onde não
  // há nem terra nem estação — era o que mais estragava o desenho.
  //
  // As estações entram no mesmo recorte: num mapa de um estado só, os pontos
  // do país inteiro apareciam boiando em volta do desenho.
  const mascara = mascaraDoMapa(projecao);
  if (mascara) contexto.clip(mascara);
  contexto.drawImage(grade, 0, 0, tela.width, tela.height);
  desenharEstacoes(contexto, pontos);
  contexto.restore();
}

/**
 * Caminho do mapa inteiro, para recortar a chuva.
 *
 * Fica guardado na projeção porque montá-lo custa — são milhares de
 * polígonos — e o interruptor da chuva pode ser ligado e desligado várias
 * vezes sobre o mesmo desenho.
 */
function mascaraDoMapa(projecao) {
  if (projecao.mascara !== undefined) return projecao.mascara;

  try {
    projecao.mascara = projecao.contorno ? new Path2D(projecao.contorno) : null;
  } catch (erro) {
    projecao.mascara = null;  // sem Path2D, a chuva só deixa de recortar
  }
  return projecao.mascara;
}

/**
 * Marca onde cada estação fica: é o que separa medição de interpolação.
 *
 * `escala` encolhe o marcador sem mudar a proporção entre o anel e o miolo.
 * Ela existe por causa do mapa de calor: a camada de chuva é esburacada, e os
 * pontos se distribuem entre manchas; a de temperatura é cheia, e os mesmos
 * 600 marcadores em cima de um campo contínuo viram um chuvisco que compete
 * com o próprio campo. Menores, continuam dizendo onde a medição é real sem
 * disputar a leitura.
 */
function desenharEstacoes(contexto, pontos, escala = 1) {
  contexto.save();
  for (const ponto of pontos) {
    // Anel escuro por fora, miolo branco por dentro. O ponto branco sozinho
    // sumia sobre o azul-claro do "quase não choveu"; um ponto escuro sozinho
    // sumiria sobre o vinho do "choveu muito". Os dois juntos aparecem em
    // qualquer lugar da escala.
    contexto.beginPath();
    contexto.arc(ponto.x, ponto.y, 2.6 * escala, 0, Math.PI * 2);
    contexto.fillStyle = "rgba(12,22,38,.55)";
    contexto.fill();

    contexto.beginPath();
    contexto.arc(ponto.x, ponto.y, 1.4 * escala, 0, Math.PI * 2);
    contexto.fillStyle = "rgba(255,255,255,.95)";
    contexto.fill();
  }
  contexto.restore();
}

const paraRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

/**
 * Transforma as faixas da API numa rampa contínua de cor.
 *
 * A API manda faixas ("60 a 120 mm", "20 a 24 °C"), que é como a legenda se
 * lê e como se fala das duas grandezas. Pintar o mapa faixa a faixa, porém,
 * desenha degraus onde o campo é contínuo, e degrau no meio da mancha parece
 * fronteira de dado. A rampa mantém exatamente as mesmas cores, ancoradas no
 * início de cada faixa, e interpola entre elas — a legenda continua
 * verdadeira.
 *
 * Serve à chuva e ao mapa de calor sem mudar nada: as duas escalas chegam da
 * API no mesmo formato, e a conta é a mesma. O que muda é só a unidade do
 * número que entra.
 */
function rampaDeCores(escala) {
  return escala.map((faixa) => ({ valor: faixa.de, cor: paraRgb(faixa.cor) }));
}

function corNaRampa(valor, rampa) {
  if (valor <= rampa[0].valor) return rampa[0].cor;

  for (let i = 1; i < rampa.length; i++) {
    if (valor >= rampa[i].valor) continue;
    const antes = rampa[i - 1], depois = rampa[i];
    const t = (valor - antes.valor) / (depois.valor - antes.valor);
    return [0, 1, 2].map(
      (c) => Math.round(antes.cor[c] + (depois.cor[c] - antes.cor[c]) * t)
    );
  }
  return rampa[rampa.length - 1].cor;
}

/**
 * Legenda da chuva: uma barra contínua, com marca em cada mudança de faixa.
 *
 * Era uma fileira de quadradinhos, um por faixa, todos do mesmo tamanho — e
 * isso dizia que "0 a 25 mm" ocupa tanto da escala quanto "300 a 450 mm". Na
 * barra, a posição de cada marca é o próprio valor: a legenda passa a ter a
 * mesma geometria do mapa que ela explica.
 */
function montarLegendaDeChuva(idLegenda, dados) {
  const escala = dados.escala;
  const topo = escala[escala.length - 1].de || 1;
  const posicao = (valor) => ((valor / topo) * 100).toFixed(1);

  const degrade = escala.map((f) => `${f.cor} ${posicao(f.de)}%`).join(", ");

  // A primeira marca seria o zero, que é o começo da barra e não precisa de
  // número; a última leva "+" porque a faixa não tem fim.
  const marcas = escala.slice(1).map((f, i) => {
    const numero = f.de.toLocaleString("pt-BR");
    const rotulo = i === escala.length - 2 ? `${numero}+` : numero;
    return `<span style="left:${posicao(f.de)}%">${rotulo}</span>`;
  }).join("");

  const legenda = $(idLegenda);
  legenda.innerHTML =
    `<span class="legenda-titulo">chuva medida (${dados.unidade})</span>
     <div class="escala-chuva">
       <div class="escala-barra" style="background:linear-gradient(90deg,${degrade})"></div>
       <div class="escala-marcas">${marcas}</div>
     </div>
     <span class="legenda-estacao"><i></i>estação do INMET</span>`;
  legenda.classList.remove("oculto");
  esconderMarcasQueColidem(legenda);

  // O container e estavel (tem id); so o miolo e refeito a cada montagem.
  // Observar duas vezes o mesmo elemento nao acumula.
  observadorDaLegenda.observe(legenda);
}

/**
 * As faixas baixas da escala ficam a poucos milímetros umas das outras, e numa
 * barra estreita — a legenda do painel tem pouco mais da metade da largura da
 * legenda do mapa grande — os primeiros rótulos se encavalam.
 *
 * A varredura vai da direita para a esquerda: a marca de maior valor é a
 * âncora e nunca some, e some o rótulo de quem não couber. Só o rótulo: a cor
 * da faixa continua na barra, que é o que a legenda explica de verdade.
 */
function esconderMarcasQueColidem(legenda) {
  const marcas = [...legenda.querySelectorAll(".escala-marcas span")];
  let bordaEsquerdaDaVizinha = null;

  for (let i = marcas.length - 1; i >= 0; i--) {
    const marca = marcas[i];
    marca.hidden = false;              // pode estar escondida de um passo anterior
    const caixa = marca.getBoundingClientRect();

    // 6px de respiro: encostar um número no outro já atrapalha a leitura.
    if (bordaEsquerdaDaVizinha !== null
        && caixa.right + 6 > bordaEsquerdaDaVizinha) {
      marca.hidden = true;
      continue;
    }
    bordaEsquerdaDaVizinha = caixa.left;
  }
}

// A largura da barra muda por muito mais motivo do que redimensionar a janela:
// a troca de palco, o painel que abre, a coluna que reflui. Nenhum deles
// dispara `resize` na window, e um rótulo descartado numa barra estreita
// continuaria sumido depois que ela crescesse. O observador pega todos, porque
// escuta o elemento e não a janela.
const observadorDaLegenda = new ResizeObserver((entradas) => {
  for (const entrada of entradas) esconderMarcasQueColidem(entrada.target);
});

// ---------------------------------------------------------------------------
// Capitais estaduais
// ---------------------------------------------------------------------------
// O mapa pinta milhares de municípios e não escreve nenhum nome. Sem
// referência nenhuma, quem olha vê manchas de cor e não sabe onde está
// olhando — e a primeira pergunta de quem vê o mapa é sempre "onde fica a
// minha cidade?". As capitais dão o ponto de apoio: achou São Paulo, achou o
// Sudeste; achou Manaus, achou o Amazonas.
//
// São só 27 marcadores, e eles não carregam dado nenhum: o risco continua
// sendo a cor do município. Por isso podem ser desligados no interruptor —
// no mapa de um estado só, o nome da capital às vezes cobre justamente o
// município que se quer olhar.

const MAPAS_COM_CAPITAIS = ["consulta", "mapa", "cidade", "ano"];

const capitalPorCodigo = new Map();      // codigo_ibge -> capital
let promessaCapitais = null;

/**
 * Busca as capitais uma vez e guarda.
 *
 * Devolve sempre a mesma promessa: os três mapas esperam por ela antes de
 * desenhar, e sem isso o primeiro deles poderia sair sem marcador nenhum,
 * só porque a lista ainda estava a caminho.
 *
 * Falhar aqui não derruba o mapa — sem a lista, os marcadores simplesmente
 * não aparecem e o resto continua igual.
 */
function carregarCapitais() {
  if (promessaCapitais) return promessaCapitais;

  promessaCapitais = (async () => {
    try {
      const dados = await pedir("/mapa/capitais");
      (dados.capitais || []).forEach((c) => capitalPorCodigo.set(c.codigo_ibge, c));
    } catch (erro) {
      /* sem capitais: o mapa continua de pé, só sem os pontos de referência */
    }
  })();

  return promessaCapitais;
}

/** Liga os interruptores "destacar as capitais" dos três mapas. */
function ligarCapitais() {
  for (const prefixo of MAPAS_COM_CAPITAIS) {
    const caixa = $(`${prefixo}-capitais`);
    const area = $(`${prefixo}-svg`).closest(".mapa-area");
    if (!caixa || !area) continue;

    const aplicar = () => area.classList.toggle("mostrar-capitais", caixa.checked);
    caixa.addEventListener("change", aplicar);
    aplicar();
  }
}

/**
 * Desenha os marcadores das capitais que aparecem no recorte atual.
 *
 * O contorno do município vem redesenhado por cima de tudo, e não como
 * classe no `path` original: com 5.570 polígonos vizinhos empilhados, o
 * traço do que foi desenhado primeiro some sob os que vieram depois.
 */
function camadaDeCapitais(contornos, presentes, px, py, largura) {
  if (!presentes.length) return "";

  const colocados = [];
  const marcas = presentes.map((c) => {
    const x = px(c.lon);
    const y = py(c.lat);
    const posicao = posicaoDoRotulo(c.nome, x, y, largura, colocados);
    colocados.push(posicao.caixa);

    return `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})">`
         + `<circle class="capital-halo" r="5.6"></circle>`
         + `<circle class="capital-ponto" r="2.4"></circle>`
         + `<text class="capital-nome" x="${posicao.dx}" y="${posicao.dy}"`
         + ` text-anchor="${posicao.ancora}">${c.nome}</text></g>`;
  });

  return contornos.map((d) => `<path class="capital-contorno" d="${d}"></path>`).join("")
       + marcas.join("");
}

// Onde o rótulo pode ir, em ordem de preferência: à direita do ponto, à
// esquerda, e depois acima e abaixo. Os valores estão nas unidades do
// viewBox, as mesmas em que o mapa é desenhado.
const LADOS_DO_ROTULO = [
  { dx: 9, dy: 3.6, ancora: "start" },
  { dx: -9, dy: 3.6, ancora: "end" },
  { dx: 9, dy: -6, ancora: "start" },
  { dx: -9, dy: -6, ancora: "end" },
  { dx: 0, dy: -9, ancora: "middle" },
  { dx: 0, dy: 16, ancora: "middle" },
];

/**
 * Escolhe de que lado do ponto o nome da capital fica.
 *
 * No Brasil inteiro, as capitais do Nordeste ficam a poucos graus umas das
 * outras: escritas todas do mesmo lado, "Recife", "Maceió" e "Aracaju" saem
 * empilhadas e nenhuma das três se lê. Cada nome tenta os lados em ordem e
 * pega o primeiro que não bate em nome já escrito nem sai do quadro.
 *
 * Quando todos batem — e num mapa cheio isso acontece — vale o último lado
 * tentado. Um nome torto ainda é melhor do que uma capital sem nome, que é o
 * que a pessoa está justamente procurando no mapa.
 */
function posicaoDoRotulo(nome, x, y, largura, colocados) {
  // Sem medir texto de verdade (custaria um canvas por rótulo), a largura sai
  // da contagem de letras. O peso 5.9 foi ajustado para a fonte em negrito de
  // 10,5 px do `.capital-nome`.
  const comprimento = nome.length * 5.9;
  const bate = (a, b) => a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1;

  let ultima = null;
  for (const lado of LADOS_DO_ROTULO) {
    const inicio = lado.ancora === "start" ? x + lado.dx
                 : lado.ancora === "end" ? x + lado.dx - comprimento
                 : x + lado.dx - comprimento / 2;

    const caixa = {
      x1: inicio, x2: inicio + comprimento,
      y1: y + lado.dy - 9, y2: y + lado.dy + 3,
    };
    ultima = { ...lado, caixa };

    if (caixa.x1 < 2 || caixa.x2 > largura - 2) continue;
    if (colocados.some((posto) => bate(caixa, posto))) continue;
    return ultima;
  }
  return ultima;
}


/** Texto da dica no mapa de risco: uma previsão do modelo. */
function dicaDeRisco(info) {
  return `<strong>${info.municipio}</strong> — ${info.uf}<br>`
       + `risco ${info.nivel_risco}<br>`
       + `chance de ser grave: ${porcento(info.probabilidade_alto)}`;
}

/**
 * Desenha um conjunto de municípios num SVG, com a cor que a API mandou.
 *
 * Serve aos três mapas — país, cidade e ano — porque não sabe o que a cor
 * significa: quem chama decide o que entra em `porMunicipio` e como a dica é
 * escrita. O enquadramento é recalculado a cada chamada, então um estado ou
 * uma região preenchem a tela em vez de virar um ponto no meio do Brasil.
 */
function renderizarSvg(idSvg, idDica, feicoes, porMunicipio, codigoEmFoco = null,
                       descrever = dicaDeRisco) {
  const svg = $(idSvg);
  const [, , LARGURA, ALTURA] = svg.getAttribute("viewBox").split(" ").map(Number);
  const MARGEM = 12;

  let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
  const visitar = (coords, aplicar) => {
    if (typeof coords[0] === "number") aplicar(coords);
    else coords.forEach((c) => visitar(c, aplicar));
  };
  feicoes.forEach((f) => visitar(f.geometry.coordinates, ([lon, lat]) => {
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }));

  const larguraGeo = Math.max(maxLon - minLon, 1e-6);
  const alturaGeo = Math.max(maxLat - minLat, 1e-6);
  const escala = Math.min((LARGURA - MARGEM * 2) / larguraGeo,
                          (ALTURA - MARGEM * 2) / alturaGeo);
  const deslocaX = (LARGURA - larguraGeo * escala) / 2;
  const deslocaY = (ALTURA - alturaGeo * escala) / 2;

  const px = (lon) => (lon - minLon) * escala + deslocaX;
  // O y do SVG cresce para baixo; a latitude cresce para cima.
  const py = (lat) => (maxLat - lat) * escala + deslocaY;

  const anelParaPath = (anel) =>
    "M" + anel.map(([lon, lat]) => `${px(lon).toFixed(1)},${py(lat).toFixed(1)}`)
              .join("L") + "Z";

  const partes = [];
  const aoFim = [];                 // o município em foco, por cima de todos
  const contorno = [];              // tudo que foi desenhado, para a chuva
  const contornosCapitais = [];
  const capitaisNoRecorte = [];

  // Onde cada município e cada estado caem no desenho. É o que a câmera usa
  // para saber até onde voar: sem isso, aproximar uma cidade exigiria varrer
  // a malha de novo a cada consulta.
  const caixas = new Map();
  const caixasUf = new Map();

  // Os caminhos de cada estado, guardados por sigla. É com eles que o destaque
  // recorta o buraco no véu — juntá-los na hora sairia do mesmo lugar, mas
  // exigiria varrer a malha inteira a cada troca no seletor.
  const dPorUf = new Map();

  const juntar = (caixa, x, y) => {
    if (x < caixa[0]) caixa[0] = x;
    if (y < caixa[1]) caixa[1] = y;
    if (x > caixa[2]) caixa[2] = x;
    if (y > caixa[3]) caixa[3] = y;
  };

  feicoes.forEach((f) => {
    const codigo = f.properties.codigo_ibge;
    const info = porMunicipio.get(codigo);
    const g = f.geometry;
    const poligonos = g.type === "Polygon" ? [g.coordinates] : g.coordinates;

    const d = poligonos.map((p) => p.map(anelParaPath).join("")).join("");
    if (!d) return;

    const caixa = [Infinity, Infinity, -Infinity, -Infinity];
    visitar(g.coordinates, ([lon, lat]) => juntar(caixa, px(lon), py(lat)));
    caixas.set(codigo, caixa);

    const uf = ufDoCodigo(codigo);
    if (uf) {
      const doEstado = caixasUf.get(uf)
        || caixasUf.set(uf, [Infinity, Infinity, -Infinity, -Infinity]).get(uf);
      juntar(doEstado, caixa[0], caixa[1]);
      juntar(doEstado, caixa[2], caixa[3]);

      if (!dPorUf.has(uf)) dPorUf.set(uf, []);
      dPorUf.get(uf).push(d);
    }

    contorno.push(d);

    const capital = capitalPorCodigo.get(codigo);
    if (capital) {
      contornosCapitais.push(d);
      capitaisNoRecorte.push(capital);
    }

    const emFoco = codigo === codigoEmFoco;
    const atributos = `data-ibge="${codigo}"${uf ? ` data-uf="${uf}"` : ""}`;

    const path = info
      ? `<path d="${d}" fill="${info.cor}" class="${emFoco ? "foco" : ""}" ${atributos}></path>`
      // Quem não tem info também leva `data-ibge`: no mapa do histórico,
      // "nenhuma ocorrência neste ano" é uma resposta legítima, e o município
      // consultado precisa poder ser destacado mesmo assim. A dica ignora
      // quem não tem info.
      : `<path d="${d}" class="sem-dado${emFoco ? " foco" : ""}" ${atributos}></path>`;

    // O município em foco vai para o fim da fila. Em SVG não existe z-index:
    // quem é desenhado por último fica por cima, e no meio da malha o traço do
    // vizinho apagava metade do anel de destaque.
    if (emFoco) aoFim.push(path); else partes.push(path);
  });

  svg.innerHTML = partes.concat(aoFim).join("");

  // As capitais vão para um <svg> próprio, sobreposto ao do mapa. Dentro do
  // mapa elas ficariam por baixo da camada de chuva, e o nome da capital
  // sumiria justamente quando a chuva está ligada.
  const camadaCapitais = $(idSvg.replace("-svg", "-capitais-svg"));
  if (camadaCapitais) {
    camadaCapitais.innerHTML =
      camadaDeCapitais(contornosCapitais, capitaisNoRecorte, px, py, LARGURA);
  }

  // Um único listener no SVG, em vez de um por município — com 5.570
  // elementos, a diferença de desempenho trava a página.
  svg.onmousemove = (evento) => {
    const alvo = evento.target.closest("path[data-ibge]");
    const dica = $(idDica);
    if (!alvo) { dica.classList.add("oculto"); return; }

    const info = porMunicipio.get(Number(alvo.dataset.ibge));
    if (!info) { dica.classList.add("oculto"); return; }

    dica.innerHTML = descrever(info);
    // A referência é a moldura do mapa, e não o próprio <svg>: nos mapas
    // grandes o SVG anda junto com a câmera, e medir por ele deixaria a dica
    // deslocada — mais errada quanto mais ampliado estivesse.
    const area = (svg.closest(".mapa-area") || svg).getBoundingClientRect();
    dica.style.left = `${Math.min(evento.clientX - area.left + 14, area.width - 270)}px`;
    dica.style.top = `${evento.clientY - area.top + 14}px`;
    dica.classList.remove("oculto");
  };
  svg.onmouseleave = () => $(idDica).classList.add("oculto");

  // A projeção fica guardada para a camada de chuva poder desenhar sobre
  // exatamente o mesmo enquadramento. Recalculá-la por fora daria um mapa
  // deslocado toda vez que o recorte mudasse (um estado, uma região).
  // `contorno` é o desenho inteiro num só caminho: a camada de chuva recorta
  // a mancha interpolada por ele, para a chuva não vazar para o mar nem para
  // fora do estado escolhido.
  // A caixa de tudo que foi desenhado. O Brasil é quase quadrado e o teatro
  // não é: enquadrar a área lógica inteira deixaria faixas vazias em volta do
  // país, e o mapa entraria menor do que cabe.
  const caixaTudo = [Infinity, Infinity, -Infinity, -Infinity];
  caixas.forEach((c) => {
    juntar(caixaTudo, c[0], c[1]);
    juntar(caixaTudo, c[2], c[3]);
  });

  projecaoDoMapa[idSvg] = {
    px, py, largura: LARGURA, altura: ALTURA, contorno: contorno.join(""),
    caixas, caixasUf, caixaTudo, dPorUf,
  };

  // O redesenho refez o SVG do zero e levou o véu junto. Se havia um estado em
  // destaque, ele volta — trocar o mês não é motivo para perder a escolha.
  aplicarFocoDeEstado(idSvg);

  return projecaoDoMapa[idSvg];
}

// Enquadramento de cada mapa, preenchido por `renderizarSvg`.
const projecaoDoMapa = {};

function montarLegenda(idLegenda, resumo) {
  const legenda = $(idLegenda);
  legenda.innerHTML =
    ["baixo", "medio", "alto"].map((nivel) =>
      `<span><i style="background:${CORES[nivel]}"></i>${nivel}`
      + ` (${resumo[nivel].toLocaleString("pt-BR")})</span>`
    ).join("")
    + amostraSemDado("sem histórico deste tipo");
  legenda.classList.remove("oculto");
}

/* A cor de "sem dado" vem da variável do CSS, e não de um hexadecimal escrito
   aqui: assim ela acompanha o tema escuro junto com o mapa que ela explica. */
function amostraSemDado(rotulo) {
  return `<span><i style="background:var(--cinza-dado)"></i>${rotulo}</span>`;
}

// ---------------------------------------------------------------------------
// Mapa por ano — o que já aconteceu
// ---------------------------------------------------------------------------
// Este mapa não passa pelo modelo: mostra o registro do Atlas, ano a ano. A
// diferença importa na leitura, e é por isso que a escala de cor é outra —
// aqui a cor conta ocorrências, não estima risco. Duas escalas iguais para
// coisas diferentes seria o jeito mais fácil de alguém confundir uma previsão
// com um fato.

function prepararMapaDoAno() {
  const tipo = $("ano-tipo");
  tipo.add(new Option("Todos os tipos", ""));
  TIPOS_DESASTRE.forEach((t) => tipo.add(new Option(formatarTipo(t), t)));

  const uf = $("ano-uf");
  uf.add(new Option("Brasil inteiro", ""));
  UFS.forEach((sigla) => uf.add(new Option(sigla, sigla)));
  uf.addEventListener("change", () => voarAteOEstado("ano", uf.value));

  $("form-ano").addEventListener("submit", (evento) => {
    evento.preventDefault();
    desenharAno(Number($("ano-escolhido").value), tipo.value);
  });
}

async function carregarAnos() {
  const seletor = $("ano-escolhido");
  try {
    const dados = await pedir("/historico/anos");
    // Do mais recente para o mais antigo: é o que quase todo mundo procura
    // primeiro, e evita rolar 35 opções até o fim da lista.
    [...dados.anos].reverse().forEach((a) => {
      seletor.add(new Option(
        `${a.ano} — ${a.ocorrencias.toLocaleString("pt-BR")} ocorrências`, a.ano
      ));
    });
    seletor.value = String(dados.ultimo_ano);
  } catch (erro) {
    $("ano-estado").textContent =
      `Não foi possível carregar os anos disponíveis: ${erro.message}`;
    $("ano-botao").disabled = true;
  }
}

// Desenho do mapa histórico em andamento, para quem precisa da geometria
// esperar por ela. `desenharMapaDoAno` trata os próprios erros, então esta
// promessa nunca rejeita: pode ser aguardada sem proteção.
let desenhoDoAno = null;

function desenharAno(ano, tipo = "") {
  desenhoDoAno = desenharMapaDoAno(ano, tipo);
  return desenhoDoAno;
}

async function desenharMapaDoAno(ano, tipo = "") {
  const botao = $("ano-botao");
  botao.disabled = true;
  botao.textContent = "Desenhando...";
  $("teatro-ano").classList.add("carregando");
  $("ano-estado").textContent = malhaCache
    ? "Reunindo as ocorrências do ano..."
    : "Baixando as fronteiras dos municípios (3 MB, só na primeira vez)...";

  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");
    await carregarCapitais();

    const filtro = tipo ? `?grupo_desastre=${tipo}` : "";
    const dados = await pedir(`/historico/ano/${ano}${filtro}`);

    const doMapa = dados.municipios;
    const porMunicipio = new Map(doMapa.map((m) => [m.codigo_ibge, m]));

    // Como no mapa de previsão: desenha o país inteiro e deixa o recorte por
    // conta da câmera.
    renderizarSvg("ano-svg", "ano-dica", malhaCache.features, porMunicipio,
                  null, dicaDeOcorrencias);
    atualizarChuva("ano");
    atualizarTemperatura("ano");
    reenquadrar("ano");

    mostrarNumerosDoAno(dados);
    montarLegendaDoAno(dados.legenda);
    mostrarMesesDoAno(dados);
    mostrarTiposDoAno(dados);

    const oQue = tipo ? formatarTipo(tipo) : "Desastres de todos os tipos";
    $("ano-estado").textContent =
      `${oQue} registrados em ${ano}, no Brasil · `
      + `${doMapa.length.toLocaleString("pt-BR")} municípios atingidos.`;
  } catch (erro) {
    $("ano-estado").textContent = `Não foi possível montar o mapa: ${erro.message}`;
    ["ano-numeros", "ano-legenda", "ano-meses", "ano-tipos"]
      .forEach((id) => $(id).classList.add("oculto"));
    $("ano-svg").innerHTML = "";
  } finally {
    $("teatro-ano").classList.remove("carregando");
    botao.disabled = false;
    botao.textContent = "Mostrar";
  }
}

function dicaDeOcorrencias(info) {
  const tipos = (info.tipos || []).map(formatarTipo).join(", ");
  const linhas = [
    `<strong>${info.municipio}</strong> — ${info.uf}`,
    `${info.ocorrencias} ocorrência(s) no ano`,
  ];
  if (tipos) linhas.push(tipos);
  if (info.mortos) linhas.push(`${info.mortos} morto(s)`);
  if (info.afetados) {
    linhas.push(`${info.afetados.toLocaleString("pt-BR")} afetados`);
  }
  return linhas.join("<br>");
}

function montarLegendaDoAno(faixas) {
  $("ano-legenda").innerHTML =
    faixas.map((f) => `<span><i style="background:${f.cor}"></i>${f.rotulo}</span>`)
      .join("")
    + amostraSemDado("nenhuma ocorrência registrada");
  $("ano-legenda").classList.remove("oculto");
}

function mostrarNumerosDoAno(dados) {
  // Os totais são sempre os do país. Antes o mapa podia vir recortado por
  // estado, e havia um segundo caminho que recontava tudo sobre o recorte;
  // agora quem recorta é a câmera, e o desenho é o Brasil inteiro — os
  // números do país descrevem exatamente o que está na tela.
  const numeros = [
    [dados.total_ocorrencias, "ocorrências"],
    [dados.municipios_atingidos, "municípios atingidos"],
    [dados.mortos, "mortos"],
    [dados.afetados, "pessoas afetadas"],
    [dados.reconhecidos, "emergências reconhecidas"],
  ];

  $("ano-numeros").innerHTML = numeros.map(([valor, rotulo]) =>
    `<div class="numero"><strong>${valor.toLocaleString("pt-BR")}</strong>`
    + `<span>${rotulo}</span></div>`
  ).join("");
  $("ano-numeros").classList.remove("oculto");
}

function mostrarMesesDoAno(dados) {
  const maximo = Math.max(...dados.por_mes, 1);
  $("ano-grafico").innerHTML = dados.por_mes.map((valor, i) =>
    `<div class="coluna" title="${MESES[i]}: ${valor} ocorrência(s)">
       <span class="coluna-valor">${valor}</span>
       <div class="coluna-barra" style="height:${(valor / maximo) * 100}%"></div>
       <span class="coluna-mes">${MESES[i].slice(0, 3)}</span>
     </div>`
  ).join("");
  $("ano-meses").classList.remove("oculto");
}

function mostrarTiposDoAno(dados) {
  const tabela = $("ano-tabela-tipos");
  tabela.innerHTML = "<tr><th>Tipo</th><th>Ocorrências</th><th>Municípios</th>"
                   + "<th>Mortos</th><th>Afetados</th></tr>";

  dados.por_tipo.forEach((t) => {
    const linha = tabela.insertRow();
    linha.insertCell().textContent = formatarTipo(t.grupo_desastre);
    [t.ocorrencias, t.municipios, t.mortos, t.afetados].forEach((valor) => {
      const celula = linha.insertCell();
      celula.className = "numero";
      celula.textContent = Number(valor).toLocaleString("pt-BR");
    });
  });
  $("ano-tipos").classList.remove("oculto");
}

// ---------------------------------------------------------------------------
// Palcos
// ---------------------------------------------------------------------------
// A página não rola: são três telas cheias — abertura, mapas e despedida — e
// só uma fica visível por vez. Quem manda é o atributo `data-palco` no <body>;
// o CSS cuida da transição, e aqui ficam só as consequências que o CSS não
// tem como ter: pausar o fundo animado que saiu de cena e desenhar o mapa na
// primeira vez que os mapas aparecem.

let fundoGlobo = null;
let fundoClima = null;
let mapaJaDesenhado = false;

function ligarPalcos() {
  fundoGlobo = Cenario.globo($("fundo-globo"));
  fundoClima = Cenario.clima($("fundo-clima"));
  fundoClima.pausar();

  $("botao-entrar").addEventListener("click", entrarNosMapas);
  // Reinicia antes de trocar de palco: a limpeza acontece atrás da cortina
  // que está subindo, e não à vista de quem ainda está olhando os mapas.
  $("botao-encerrar").addEventListener("click", () => {
    reiniciarExperiencia();
    trocarPalco("despedida");
  });
  $("botao-reiniciar").addEventListener("click", () => trocarPalco("abertura"));

  ligarGaveta();
}

function trocarPalco(nome) {
  document.body.dataset.palco = nome;

  // Só um dos dois cenários desenha por vez. O outro continua existindo, com
  // o estado intacto, mas sem gastar quadro nenhum atrás de uma tela que
  // ninguém está vendo.
  ventosEmCena(nome === "mapas" && mapaAtivo === "mapa");

  if (nome === "mapas") {
    fundoGlobo?.pausar();
    fundoClima?.seguir();
  } else {
    fundoClima?.pausar();
    fundoGlobo?.seguir();
    // Fora dos mapas o globo volta a ser fundo. Sem desfazer o mergulho, a
    // despedida abriria com o planeta congelado em cima do Brasil, e a
    // abertura seguinte nunca mais teria um globo para girar.
    document.body.classList.remove("mergulhando");
    fundoGlobo?.restaurar();
  }

  if (nome === "mapas") garantirMapaDesenhado();
}

// O ponto do globo onde a câmera pousa. Não é o centroide exato do país: é o
// enquadramento que deixa o Brasil inteiro dentro do disco, do Oiapoque ao
// Chuí, sem sobrar oceano de um lado só.
const BRASIL_NO_GLOBO = { lon: -53, lat: -14 };
const MERGULHO_S = 1.9;

/**
 * A entrada nos mapas: o globo desce até o Brasil e entrega a tela ao mapa.
 *
 * O desenho do mapa começa junto com o mergulho, e não depois dele. São 3 MB
 * de fronteiras e alguns segundos de cálculo no servidor — pedir isso só na
 * troca de palco faria a viagem terminar num teatro vazio, que é exatamente o
 * contrário do que a animação acabou de prometer. Os dois correm juntos, e a
 * descida serve de espera.
 */
async function entrarNosMapas() {
  const botao = $("botao-entrar");
  if (botao.disabled) return;   // a descida já começou; o segundo clique não conta
  botao.disabled = true;

  garantirMapaDesenhado();
  document.body.classList.add("mergulhando");

  // Em aba escondida o navegador não entrega quadro nenhum, e o mergulho
  // ficaria pendurado para sempre — levando junto o clique que espera por ele.
  // O mesmo problema que o voo da câmera dos mapas resolve com `concluir`.
  await Promise.race([
    fundoGlobo?.mergulhar({ ...BRASIL_NO_GLOBO, duracao: MERGULHO_S })
      ?? Promise.resolve(),
    esperar(MERGULHO_S * 1000 + 600),
  ]);

  trocarPalco("mapas");
  botao.disabled = false;
}

/** Desenha o mapa da previsão uma vez só, quando ele passa a ser preciso. */
function garantirMapaDesenhado() {
  if (mapaJaDesenhado) return;
  mapaJaDesenhado = true;
  // Entrar num mapa vazio e ter de apertar "Desenhar" para ver qualquer coisa
  // é um passo a mais sem nenhuma informação nova. O país já vem pintado, e a
  // pessoa começa mexendo, não configurando.
  desenharMapa($("mapa-tipo").value, Number($("mapa-mes").value));
}

// ---------------------------------------------------------------------------
// Reinício da experiência
// ---------------------------------------------------------------------------
// "Encerrar" termina a apresentação, e a próxima começa do zero: quem assume o
// computador depois não deveria herdar o município, o tipo, o mês e o zoom de
// quem estava antes. Sem isto, voltar aos mapas trazia de volta a última
// consulta — o mapa ainda ampliado em algum estado, o painel da direita cheio
// e o formulário preenchido.
//
// O que NÃO é reiniciado, de propósito: o aviso do modelo, que pode estar
// dizendo que a API caiu; e os caches de malha e capitais, que são download e
// não escolha — refazê-los custaria 3 MB a cada reinício.

function reiniciarExperiencia() {
  reiniciarConsulta();
  reiniciarPainel();
  reiniciarMapaDaPrevisao();
  reiniciarMapaDoHistorico();
  fecharGaveta();
  mostrarMapa("mapa");
}

/** O formulário da esquerda, como ele nasce. */
function reiniciarConsulta() {
  clearTimeout(temporizadorBusca);
  temporizadorBusca = null;
  municipioEscolhido = null;

  // O campo de busca pode estar desabilitado por `bloquearFormulario`, quando
  // a API não respondeu. Reabri-lo aqui esconderia um problema que continua de
  // pé, então só o conteúdo é limpo — nunca o `disabled`.
  $("busca").value = "";
  $("sugestoes").innerHTML = "";
  $("sugestoes").classList.add("oculto");
  $("municipio-escolhido").textContent = "";
  $("municipio-escolhido").classList.add("oculto");
  $("botao").disabled = true;

  $("tipo").selectedIndex = 0;
  $("mes").value = String(new Date().getMonth() + 1);
}

/** A coluna da direita volta a ser o convite a escolher um município. */
function reiniciarPainel() {
  [
    "resultado", "consulta-mapa", "secao-ano", "secao-cidade",
    "secao-historico", "ano-meses", "ano-tipos",
  ].forEach((id) => $(id).classList.add("oculto"));
  $("painel-vazio").classList.remove("oculto");

  // Esconder não basta: o conteúdo continuaria ali, e a seção reapareceria com
  // os dados da consulta anterior no intervalo entre pedir a próxima previsão
  // e ela chegar.
  [
    "barras", "grafico", "tabela-features", "tabela-historico",
    "ano-grafico", "ano-tabela-tipos",
    "consulta-svg", "consulta-capitais-svg", "cidade-svg", "cidade-capitais-svg",
  ].forEach((id) => { $(id).innerHTML = ""; });

  ["resultado-titulo", "resultado-detalhe", "historico-resumo",
   "cidade-setores"].forEach((id) => { $(id).textContent = ""; });

  $("selo").textContent = "—";
  $("selo").className = "selo";

  // Os dois mapinhas do painel deixaram de existir: o enquadramento guardado
  // deles apontaria para um desenho que não está mais lá.
  delete projecaoDoMapa["consulta-svg"];
  delete projecaoDoMapa["cidade-svg"];

  ["consulta", "cidade"].forEach(reiniciarCamadas);
  ["consulta-legenda", "cidade-legenda"].forEach(
    (id) => $(id).classList.add("oculto")
  );
}

/** O mapa grande da previsão: filtros, câmera e desenho, todos do zero. */
function reiniciarMapaDaPrevisao() {
  $("mapa-tipo").value = "INUNDACAO";
  $("mapa-mes").value = "2";
  $("mapa-uf").value = "";
  reiniciarCamadas("mapa");

  $("mapa-svg").innerHTML = "";
  $("mapa-capitais-svg").innerHTML = "";
  $("mapa-estado").textContent = "";
  $("mapa-legenda").classList.add("oculto");
  delete projecaoDoMapa["mapa-svg"];

  reiniciarCamera("mapa");

  // O desenho não é refeito agora: quem encerra pode nunca mais voltar aos
  // mapas, e redesenhar custa uma chamada à API. Marcar como não desenhado faz
  // `trocarPalco` refazê-lo na volta — o mesmo caminho da primeira vez, com o
  // palco já em cena.
  mapaJaDesenhado = false;
}

/** O mapa grande do histórico, idem. */
function reiniciarMapaDoHistorico() {
  // Os anos vêm do mais recente para o mais antigo, então o primeiro da lista
  // é o mesmo que `carregarAnos` deixou escolhido.
  $("ano-escolhido").selectedIndex = 0;
  $("ano-tipo").value = "";
  $("ano-uf").value = "";
  reiniciarCamadas("ano");

  $("ano-svg").innerHTML = "";
  $("ano-capitais-svg").innerHTML = "";
  $("ano-estado").textContent = "";
  $("ano-legenda").classList.add("oculto");
  $("ano-numeros").classList.add("oculto");
  $("ano-numeros").innerHTML = "";
  delete projecaoDoMapa["ano-svg"];

  reiniciarCamera("ano");

  // `mostrarMapa` redesenha o histórico quando o SVG está vazio, na primeira
  // vez que alguém abrir a aba de novo.
  desenhoDoAno = null;
}

/** Capitais ligadas, chuva desligada — e o canvas da chuva limpo junto. */
function reiniciarCamadas(prefixo) {
  const capitais = $(`${prefixo}-capitais`);
  if (capitais) {
    capitais.checked = true;
    $(`${prefixo}-svg`).closest(".mapa-area")
      ?.classList.add("mostrar-capitais");
  }

  const chuva = $(`${prefixo}-chuva`);
  if (chuva) {
    chuva.checked = false;
    // Desmarcar por código não dispara `change`. Chamar `atualizarChuva` é o
    // que apaga o canvas, tira a legenda e devolve a cor ao mapa de baixo.
    atualizarChuva(prefixo);
  }

  const vento = $(`${prefixo}-vento`);
  if (vento) {
    vento.checked = false;
    // Aqui a chamada é ainda mais necessária que na chuva: além de limpar, é
    // ela que para o laço de animação das partículas.
    atualizarVento(prefixo);
  }

  const temperatura = $(`${prefixo}-temperatura`);
  if (temperatura) {
    temperatura.checked = false;
    // Mesmo motivo da chuva: desmarcar por código não dispara `change`, e sem
    // a chamada o canvas ficaria com o campo do mapa anterior por cima do
    // novo — um mapa de calor do Brasil inteiro em cima de um município.
    atualizarTemperatura(prefixo);
  }
}

/** Devolve a câmera ao país inteiro, sem voo e sem estado marcado. */
function reiniciarCamera(prefixo) {
  const estado = cameras[prefixo];
  // Um voo em curso continuaria animando por cima do reinício e pousaria de
  // volta no município de onde acabamos de sair.
  if (estado.animacao) cancelAnimationFrame(estado.animacao);
  estado.animacao = null;
  estado.concluir = null;
  estado.caixa = null;

  destacarEstado(`${prefixo}-svg`, null);
  $(`${prefixo}-voltar`).classList.add("oculto");
  $(`teatro-${prefixo}`).classList.remove("ampliado", "voando");
}

function ligarGaveta() {
  const abrir = () => {
    $("gaveta").classList.remove("oculto");
    $("gaveta-fundo").classList.remove("oculto");
  };

  $("botao-saiba").addEventListener("click", abrir);
  $("gaveta-fechar").addEventListener("click", fecharGaveta);
  $("gaveta-fundo").addEventListener("click", fecharGaveta);
  addEventListener("keydown", (e) => { if (e.key === "Escape") fecharGaveta(); });
}

function fecharGaveta() {
  $("gaveta").classList.add("oculto");
  $("gaveta-fundo").classList.add("oculto");
}

// ---------------------------------------------------------------------------
// Abas: os dois mapas
// ---------------------------------------------------------------------------

let mapaAtivo = "mapa";

function ligarAbas() {
  document.querySelectorAll(".aba").forEach((aba) => {
    aba.addEventListener("click", () => mostrarMapa(aba.dataset.mapa));
  });
  ajustarConsultaPara(mapaAtivo);
}

/**
 * Faz o bloco de consulta dizer o que ele realmente faz na aba atual.
 *
 * O rótulo do botão é o que promete o resultado. Um "Prever risco" na aba do
 * histórico prometia uma previsão e entregava outra coisa; e o mês, que só
 * existe para a previsão, não tem sentido diante de um registro que cobre o
 * período inteiro.
 */
function ajustarConsultaPara(prefixo) {
  const historico = prefixo === "ano";

  $("campo-mes").classList.toggle("oculto", historico);
  $("botao").textContent = historico ? "Ver histórico" : "Prever risco";
  $("consulta-ajuda").textContent = historico
    ? "Escolha a cidade e o tipo. O mapa voa até o município e mostra o que "
      + "já foi registrado ali — nenhuma previsão."
    : "Escolha a cidade, o tipo e o mês. O mapa voa do Brasil até o estado "
      + "e pousa no município.";
}

function mostrarMapa(prefixo) {
  mapaAtivo = prefixo;

  document.querySelectorAll(".aba").forEach((aba) => {
    const ativa = aba.dataset.mapa === prefixo;
    aba.classList.toggle("ativa", ativa);
    aba.setAttribute("aria-selected", String(ativa));
  });

  $("teatro-mapa").classList.toggle("ativo", prefixo === "mapa");
  $("teatro-ano").classList.toggle("ativo", prefixo === "ano");
  $("controles-mapa").classList.toggle("oculto", prefixo !== "mapa");
  $("controles-ano").classList.toggle("oculto", prefixo !== "ano");
  ajustarConsultaPara(prefixo);

  // A coluna da direita acompanha: os blocos da outra aba saem de cena sem
  // perder o que ja carregaram, e voltam inteiros quando a aba volta.
  $("painel").dataset.aba = prefixo;

  // O vento é só da aba da previsão: os três mapas que o têm escolhem um mês,
  // e o histórico escolhe um ano.
  ventosEmCena(prefixo === "mapa");

  // O teatro escondido tinha largura zero enquanto estava fora de cena, e o
  // enquadramento calculado ali não valeria nada. Refazê-lo ao aparecer é o
  // que evita o mapa entrar cortado ou minúsculo.
  requestAnimationFrame(() => reenquadrar(prefixo));

  // O histórico só é desenhado quando alguém pede para vê-lo: são 35 anos de
  // opções, e adivinhar qual interessa custaria uma chamada à toa.
  if (prefixo === "ano" && !$("ano-svg").innerHTML && !$("ano-botao").disabled) {
    desenharAno(Number($("ano-escolhido").value), $("ano-tipo").value);
  }
}

// ---------------------------------------------------------------------------
// Câmera: o voo do Brasil até o município
// ---------------------------------------------------------------------------
// Os dois mapas grandes são desenhados sempre com o país inteiro, num sistema
// de coordenadas fixo de 1000x820. Aproximar um estado ou uma cidade não
// redesenha nada: move-se a câmera, que é uma transformação CSS aplicada ao
// elemento que contém as três camadas (mapa, chuva e capitais) de uma vez.
//
// Redesenhar por recorte, como era antes, obrigava a refazer 5.570 polígonos
// a cada mudança e fazia o enquadramento saltar. Movendo a câmera, o mesmo
// desenho é reaproveitado e o caminho entre os dois enquadramentos fica
// visível — que é justamente o que conta a história de onde fica a cidade.

const CAMERA_LARGURA = 1000;
const CAMERA_ALTURA = 820;
const CAIXA_LOGICA = [0, 0, CAMERA_LARGURA, CAMERA_ALTURA];

// Estado corrente de cada câmera, e a caixa que ela está enquadrando.
// `caixa: null` significa "o país inteiro", resolvido na hora — o desenho
// pode ainda nem existir quando a câmera é ligada.
const cameras = {
  mapa: { escala: 1, x: 0, y: 0, caixa: null, animacao: null, concluir: null },
  ano: { escala: 1, x: 0, y: 0, caixa: null, animacao: null, concluir: null },
};

/** A caixa que contém o país inteiro naquele mapa. */
function caixaDoPais(prefixo) {
  const projecao = projecaoDoMapa[`${prefixo}-svg`];
  return (projecao && projecao.caixaTudo) || CAIXA_LOGICA;
}

function ligarCamera() {
  // Voltar ao país inteiro apaga o destaque junto: um estado marcado num mapa
  // do Brasil todo diria que o recorte ainda vale, e ele não vale mais.
  const verOBrasil = (prefixo) => {
    $(`${prefixo}-uf`).value = "";
    destacarEstado(`${prefixo}-svg`, null);
    voar(prefixo, null);
  };

  $("mapa-voltar").addEventListener("click", () => verOBrasil("mapa"));
  $("ano-voltar").addEventListener("click", () => verOBrasil("ano"));

  // Aba escondida não recebe quadro nenhum, e um voo em curso ficaria parado
  // no meio do caminho sem nunca terminar. Ele é concluído no destino.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) return;
    Object.values(cameras).forEach((estado) => estado.concluir?.());
  });

  // Mudar o tamanho da janela muda o tamanho do teatro, e o enquadramento
  // guardado deixa de caber. Refazê-lo mantém exatamente a mesma vista.
  let espera = null;
  addEventListener("resize", () => {
    clearTimeout(espera);
    espera = setTimeout(() => {
      reenquadrar("mapa");
      reenquadrar("ano");
    }, 120);
  });
}

/** Escala e centro que fazem `caixa` preencher o teatro de `prefixo`. */
function enquadramento(prefixo, caixa) {
  const teatro = $(`teatro-${prefixo}`);
  const largura = teatro.clientWidth || 1;
  const altura = teatro.clientHeight || 1;

  const [x0, y0, x1, y1] = caixa;
  const larguraCaixa = Math.max(x1 - x0, 0.5);
  const alturaCaixa = Math.max(y1 - y0, 0.5);

  // A folga de 12% impede que o município encoste nas bordas do teatro, e o
  // teto de 45x é onde a malha simplificada do IBGE começa a mostrar os
  // próprios vértices — passar disso amplia o erro do dado, não o dado.
  const escala = Math.min(largura / larguraCaixa, altura / alturaCaixa) * 0.88;

  return {
    escala: Math.min(escala, 45),
    x: (x0 + x1) / 2,
    y: (y0 + y1) / 2,
  };
}

function aplicarCamera(prefixo, escala, x, y) {
  const teatro = $(`teatro-${prefixo}`);
  const camera = $(`camera-${prefixo}`);
  const deslocaX = teatro.clientWidth / 2 - escala * x;
  const deslocaY = teatro.clientHeight / 2 - escala * y;
  camera.style.transform =
    `translate(${deslocaX.toFixed(2)}px, ${deslocaY.toFixed(2)}px) `
    + `scale(${escala.toFixed(5)})`;
  // O CSS divide a espessura dos traços por esta escala, para que fronteiras e
  // contorno de foco tenham sempre a mesma grossura na tela, em qualquer zoom.
  camera.style.setProperty("--zoom", escala.toFixed(5));

  const estado = cameras[prefixo];
  estado.escala = escala;
  estado.x = x;
  estado.y = y;

  // Ampliado, o nome da capital vira um letreiro atravessado na tela e cobre
  // justamente o município que a câmera foi buscar.
  const base = enquadramento(prefixo, caixaDoPais(prefixo)).escala;
  teatro.classList.toggle("ampliado", escala > base * 2.2);
  $(`${prefixo}-voltar`).classList.toggle("oculto", escala <= base * 1.05);

  // O mapa de calor desenha os marcadores das estações no tamanho dividido
  // pela ampliação, então ele precisa refazer-se quando ela muda. O pedido
  // sai daqui porque este é o único caminho por onde a câmera passa; o
  // adiamento de quem recebe é que garante um redesenho só, no fim do voo.
  agendarRedesenhoDoCalor(prefixo);
}

/** Põe o enquadramento guardado de volta, sem animação. */
function reenquadrar(prefixo) {
  const estado = cameras[prefixo];
  // Um voo em curso já sabe para onde está indo. Reenquadrar por baixo dele —
  // é o que o fim de um redesenho faria — daria um salto no meio do caminho.
  if (estado.animacao) return;

  const alvo = enquadramento(prefixo, estado.caixa || caixaDoPais(prefixo));
  aplicarCamera(prefixo, alvo.escala, alvo.x, alvo.y);
}

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Leva a câmera até `caixa`, animando.
 *
 * O centro caminha em linha reta, mas a escala cresce em progressão
 * geométrica: dobrar de 1 para 2 e dobrar de 40 para 80 têm de parecer o
 * mesmo movimento, e é o que acontece quando se interpola o logaritmo. Com
 * interpolação linear, um voo até uma cidade pequena passaria quase todo o
 * tempo parado no começo e terminaria num salto.
 */
function voar(prefixo, caixa, duracao = 1200) {
  const estado = cameras[prefixo];
  estado.caixa = caixa;

  if (estado.animacao) cancelAnimationFrame(estado.animacao);

  const partida = { escala: estado.escala, x: estado.x, y: estado.y };
  const destino = enquadramento(prefixo, caixa || caixaDoPais(prefixo));

  // Sem animação a pedido do sistema, ou com a página escondida, a câmera vai
  // direto ao destino. O caso da página escondida não é detalhe: em aba
  // oculta o navegador não entrega quadro nenhum, e um voo que esperasse por
  // eles nunca terminaria — deixando a previsão pendurada em "Calculando..."
  // até alguém voltar para a aba.
  if (Cenario.reduzido || document.hidden) {
    aplicarCamera(prefixo, destino.escala, destino.x, destino.y);
    estado.animacao = null;
    return Promise.resolve();
  }

  return new Promise((pronto) => {
    const inicio = performance.now();

    // Encerrar o voo no destino, agora. Fica guardado no estado porque quem
    // precisa chamá-lo pode estar fora daqui: em aba oculta o navegador para
    // de entregar quadros, e o voo em curso não teria como saber disso
    // sozinho — ficaria pendurado, e com ele a previsão inteira, presa em
    // "Calculando..." até alguém voltar para a aba.
    estado.concluir = () => {
      if (estado.animacao) cancelAnimationFrame(estado.animacao);
      estado.animacao = null;
      estado.concluir = null;
      $(`teatro-${prefixo}`).classList.remove("voando");
      aplicarCamera(prefixo, destino.escala, destino.x, destino.y);
      pronto();
    };

    $(`teatro-${prefixo}`).classList.add("voando");

    const passo = (agora) => {
      const t = Math.min((agora - inicio) / duracao, 1);
      // Suavização nas duas pontas: sai devagar, ganha velocidade no meio,
      // pousa devagar. É o que faz o movimento parecer uma câmera, e não um
      // corte.
      const s = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

      const escala = partida.escala
        * Math.pow(destino.escala / partida.escala, s);
      aplicarCamera(
        prefixo,
        escala,
        partida.x + (destino.x - partida.x) * s,
        partida.y + (destino.y - partida.y) * s,
      );

      if (t < 1) {
        estado.animacao = requestAnimationFrame(passo);
      } else {
        estado.animacao = null;
        estado.concluir = null;
        $(`teatro-${prefixo}`).classList.remove("voando");
        pronto();
      }
    };

    estado.animacao = requestAnimationFrame(passo);
  });
}

/**
 * O voo completo: do país ao estado, uma pausa, e do estado ao município.
 *
 * A parada no estado é o ponto da animação. Sem ela o Brasil vira um borrão e
 * quem assiste perde a referência de onde a cidade fica; com ela, a escala
 * intermediária dá tempo de reconhecer o estado antes de a câmera fechar.
 */
async function voarAteOMunicipio(prefixo, codigoIbge) {
  const projecao = projecaoDoMapa[`${prefixo}-svg`];
  if (!projecao || !projecao.caixas) return;

  const doMunicipio = projecao.caixas.get(codigoIbge);
  if (!doMunicipio) return;

  const uf = ufDoCodigo(codigoIbge);
  const doEstado = projecao.caixasUf.get(uf);

  if (doEstado) {
    // O estado da cidade consultada acende junto com a parada nele. É o mesmo
    // destaque do seletor "Voar até o estado", e é o que dá o endereço da
    // cidade: o município em foco sozinho, no meio da malha, não diz em que
    // parte do país está.
    destacarEstado(`${prefixo}-svg`, uf);
    $(`${prefixo}-uf`).value = uf;
    await voar(prefixo, doEstado, 1100);
    await esperar(420);
  }
  await voar(prefixo, folgar(doMunicipio, 2.6), 1300);
}

/**
 * Afasta a caixa de um município, para ele não chegar sozinho na tela.
 *
 * Um município enquadrado justo perde o contexto: sem nenhum vizinho em volta,
 * o polígono podia estar em qualquer lugar do país. A folga traz o entorno
 * junto, que é o que localiza a cidade.
 */
function folgar([x0, y0, x1, y1], fator) {
  const meioX = (x0 + x1) / 2;
  const meioY = (y0 + y1) / 2;
  // Um piso de meio ponto evita que município minúsculo seja ampliado ao
  // ponto de a malha virar um borrão de vértices.
  const metadeLargura = Math.max((x1 - x0) / 2, 0.5) * fator;
  const metadeAltura = Math.max((y1 - y0) / 2, 0.5) * fator;
  return [
    meioX - metadeLargura, meioY - metadeAltura,
    meioX + metadeLargura, meioY + metadeAltura,
  ];
}

/** Marca um município como o que está em foco no mapa grande. */
function destacarNoMapa(prefixo, codigoIbge) {
  const svg = $(`${prefixo}-svg`);
  svg.querySelectorAll("path.foco").forEach((p) => p.classList.remove("foco"));
  const alvo = svg.querySelector(`path[data-ibge="${codigoIbge}"]`);
  if (!alvo) return;

  alvo.classList.add("foco");
  // Por cima de todos, e antes do véu do estado: o anel de destaque é a última
  // coisa do mapa que ainda pode ser coberta por outro polígono.
  const veu = svg.querySelector(".uf-foco-camada");
  if (veu) svg.insertBefore(alvo, veu); else svg.appendChild(alvo);
}

// Qual estado está em destaque em cada mapa. Fica fora do SVG porque o
// redesenho o apaga, e a escolha do seletor não deve morrer junto.
const focoDeEstado = {};

/**
 * Destaca um estado no mapa — ou tira o destaque, quando a sigla é vazia.
 *
 * O desenho é por subtração: uma camada cobre o mapa inteiro com um buraco no
 * formato do estado. O caminho é o retângulo do mapa seguido dos polígonos do
 * estado, com `fill-rule="evenodd"`: onde o retângulo e um município se
 * sobrepõem, o preenchimento se cancela.
 *
 * A alternativa seria calcular a união dos polígonos do estado e traçar essa
 * fronteira. Daria o mesmo contorno, custando um algoritmo de geometria e uma
 * varredura de centenas de polígonos a cada troca no seletor.
 */
function destacarEstado(idSvg, sigla) {
  focoDeEstado[idSvg] = sigla || null;
  aplicarFocoDeEstado(idSvg);
}

function aplicarFocoDeEstado(idSvg) {
  const svg = $(idSvg);
  if (!svg) return;

  svg.querySelector(".uf-foco-camada")?.remove();

  const sigla = focoDeEstado[idSvg];
  const caminhos = sigla && projecaoDoMapa[idSvg]?.dPorUf?.get(sigla);
  if (!caminhos || !caminhos.length) {
    delete svg.dataset.ufFoco;
    return;
  }

  const [, , largura, altura] = svg.getAttribute("viewBox").split(" ").map(Number);
  const camada = document.createElementNS("http://www.w3.org/2000/svg", "g");
  camada.setAttribute("class", "uf-foco-camada");
  camada.innerHTML =
    `<path class="veu-fora" fill-rule="evenodd"`
    + ` d="M0,0H${largura}V${altura}H0Z${caminhos.join("")}"></path>`;

  svg.appendChild(camada);
  svg.dataset.ufFoco = sigla;
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
