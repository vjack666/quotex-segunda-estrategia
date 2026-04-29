import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Calculadora de Binarias',
      theme: ThemeData.dark(),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  static const String _saldoKey = 'saldo_guardado';

  final TextEditingController saldoController =
      TextEditingController(text: '0');
  final TextEditingController incrementoController =
      TextEditingController(text: '2');
  final TextEditingController payoutController =
      TextEditingController(text: '92');
  final TextEditingController multiplicadorController =
      TextEditingController(text: '2');
  final TextEditingController objetivoManualController =
      TextEditingController();

  double saldoActual = 0;
  double payout = 0.92;
  int incremento = 2;
  double saldoObjetivo = 2;

  double inversionBase = 0;
  double inversionActual = 0;

  int perdidas = 0;
  String mensaje = '';
  bool _saldoInicialCargado = false;
  List<double> historialSaldo = [];

  bool usarMultiplicador = false;

  bool get regla10Activa => saldoActual > 50;

  double? leerObjetivoManual() {
    final String raw = objetivoManualController.text.trim();
    if (raw.isEmpty) {
      return null;
    }
    return double.tryParse(raw.replaceAll(',', '.'));
  }

  double calcularObjetivo(double saldo, int paso) {
    final int base = saldo.floor();
    final int siguiente = base + paso;
    return siguiente.toDouble();
  }

  void recalcularObjetivoYBase() {
    final double? objetivoManual = leerObjetivoManual();
    if (objetivoManual != null && objetivoManual > saldoActual) {
      saldoObjetivo = objetivoManual;
    } else {
      saldoObjetivo = calcularObjetivo(saldoActual, incremento);
    }

    final double utilidadNecesaria = saldoObjetivo - saldoActual;

    if (payout <= 0) {
      inversionBase = 0;
      inversionActual = 0;
      return;
    }

    inversionBase = utilidadNecesaria > 0 ? utilidadNecesaria / payout : 0;
    inversionActual = inversionBase;
  }

  @override
  void initState() {
    super.initState();
    _cargarSaldoGuardado();
  }

  void _registrarSaldoEnHistorial() {
    if (historialSaldo.isEmpty || historialSaldo.last != saldoActual) {
      historialSaldo.add(saldoActual);
    }
  }

  Future<void> _cargarSaldoGuardado() async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    final double saldoGuardado = prefs.getDouble(_saldoKey) ?? 0;

    if (!mounted) {
      return;
    }

    setState(() {
      saldoActual = saldoGuardado;
      saldoController.text = saldoGuardado.toStringAsFixed(2);
      recalcularObjetivoYBase();
      historialSaldo = [saldoGuardado];
      _saldoInicialCargado = true;
      mensaje = saldoGuardado == 0
          ? 'Configura tu saldo inicial para comenzar.'
          : 'Saldo recuperado: \$${saldoGuardado.toStringAsFixed(2)}';
    });
  }

  Future<void> _guardarSaldo() async {
    if (!_saldoInicialCargado) {
      return;
    }

    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(_saldoKey, saldoActual);
  }

  void recalcular() {
    setState(() {
      saldoActual = double.tryParse(saldoController.text) ?? 0;
      incremento = int.tryParse(incrementoController.text) ?? 1;
      payout =
          (double.tryParse(payoutController.text) ?? 92) / 100;

      // Reinicia el ciclo con objetivo entero por escalones.
      recalcularObjetivoYBase();
      perdidas = 0;
      mensaje = '';
      _registrarSaldoEnHistorial();
    });

    _guardarSaldo();
  }

  void onGano() {
    setState(() {
      final double ganancia = inversionActual * payout;
      saldoActual += ganancia;

      // Forzamos cierre limpio del ciclo en el objetivo entero.
      saldoActual = saldoObjetivo;
      saldoController.text = saldoActual.toStringAsFixed(2);

      // Objetivo manual es de un solo uso por ciclo.
      objetivoManualController.clear();

      perdidas = 0;
      recalcularObjetivoYBase();
      _registrarSaldoEnHistorial();

      mensaje =
          '✅ Ganaste +\$${ganancia.toStringAsFixed(2)} | objetivo: \$${saldoActual.toStringAsFixed(2)}';
    });

    _guardarSaldo();
  }

  void onPerdio() {
    setState(() {
      saldoActual -= inversionActual;
      if (saldoActual < 0) {
        saldoActual = 0;
      }
      saldoController.text = saldoActual.toStringAsFixed(2);

      perdidas++;

      if (!regla10Activa && perdidas >= 3) {
        perdidas = 0;
        recalcularObjetivoYBase();
        _registrarSaldoEnHistorial();
        mensaje = '🔄 Reset gale por 3 pérdidas (saldo <= \$50)';
        return;
      }

      double siguiente;

      if (usarMultiplicador) {
        double mult =
            double.tryParse(multiplicadorController.text) ?? 2;
        siguiente = inversionActual * mult;
      } else {
        final double utilidadNecesaria = saldoObjetivo - saldoActual;
        siguiente = payout > 0
            ? (utilidadNecesaria > 0 ? utilidadNecesaria / payout : 0)
            : 0;
      }

      int limite = (saldoActual * 0.10).floor();
      int siguienteEnMostrar = siguiente.round();

      if (regla10Activa && siguienteEnMostrar >= limite) {
        // RESET AUTOMÁTICO
        perdidas = 0;
        recalcularObjetivoYBase();

        mensaje =
            '⚠️ Reset por riesgo (>10% de la cuenta)';
        return;
      }

      inversionActual = siguiente;
      _registrarSaldoEnHistorial();
      mensaje = '❌ Perdiste - Gale $perdidas';
    });

    _guardarSaldo();
  }

  Widget buildCalculadora() {
    final double? objetivoManual = leerObjetivoManual();
    final bool objetivoManualValido =
        objetivoManual != null && objetivoManual > saldoActual;

    final int limite = (saldoActual * 0.10).floor();
    final int inversionMostrada = inversionActual.round();
    final String estadoRegla = regla10Activa
        ? 'Regla 10% activa (saldo > \$50)'
        : 'Regla 10% inactiva (saldo <= \$50)';

    return Padding(
      padding: const EdgeInsets.all(16),
      child: SingleChildScrollView(
        child: Column(
          children: [
            TextField(
              controller: saldoController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Saldo'),
              onChanged: (_) => recalcular(),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: incrementoController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Incremento (\$)'),
              onChanged: (_) => recalcular(),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: payoutController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Payout (%)'),
              onChanged: (_) => recalcular(),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: objetivoManualController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'Objetivo manual (ej: 100)',
              ),
              onChanged: (_) => recalcular(),
            ),
            const SizedBox(height: 6),
            Text(
              objetivoManualController.text.trim().isEmpty
                  ? 'Modo automático por incremento'
                  : objetivoManualValido
                      ? 'Objetivo manual activo'
                      : 'Objetivo manual inválido (debe ser mayor al saldo)',
              style: TextStyle(
                fontSize: 12,
                color: objetivoManualController.text.trim().isEmpty
                    ? Colors.grey
                    : objetivoManualValido
                        ? Colors.greenAccent
                        : Colors.orangeAccent,
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                const Text('Modo Multiplicador'),
                Switch(
                  value: usarMultiplicador,
                  onChanged: (v) {
                    setState(() => usarMultiplicador = v);
                  },
                )
              ],
            ),
            if (usarMultiplicador)
              TextField(
                controller: multiplicadorController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Multiplicador'),
                onChanged: (_) => recalcular(),
              ),
            const SizedBox(height: 20),
            Text('💰 Saldo: \$${saldoActual.toStringAsFixed(2)}',
                style: const TextStyle(fontSize: 20)),
            const SizedBox(height: 8),
            Text('🏁 Objetivo: \$${saldoObjetivo.toStringAsFixed(2)}',
                style: const TextStyle(fontSize: 16)),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  '🎯 \$${inversionActual.toStringAsFixed(2)}',
                  style: const TextStyle(
                      fontSize: 26, fontWeight: FontWeight.bold),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.content_copy, size: 22),
                  tooltip: 'Copiar monto',
                  onPressed: () {
                    Clipboard.setData(
                      ClipboardData(text: inversionActual.toStringAsFixed(2)),
                    );
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(
                          'Copiado: \$${inversionActual.toStringAsFixed(2)}',
                        ),
                        duration: const Duration(seconds: 1),
                      ),
                    );
                  },
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text('🔁 Gale: $perdidas', style: const TextStyle(fontSize: 18)),
            const SizedBox(height: 8),
            Text('⚠️ Límite 10%: \$$limite',
                style: const TextStyle(fontSize: 16)),
            const SizedBox(height: 4),
            Text(
              estadoRegla,
              style: TextStyle(
                fontSize: 13,
                color:
                    regla10Activa ? Colors.greenAccent : Colors.orangeAccent,
              ),
            ),
            const SizedBox(height: 10),
            if (regla10Activa && inversionMostrada >= limite)
              const Text(
                '🔴 RIESGO ALTO',
                style: TextStyle(
                  color: Colors.red,
                  fontWeight: FontWeight.bold,
                  fontSize: 16,
                ),
              ),
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.grey[800],
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                mensaje.isEmpty ? 'Esperando acción...' : mensaje,
                style: const TextStyle(fontSize: 14),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton(
                    onPressed: onGano,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                    child: const Text(
                      'GANÓ',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: ElevatedButton(
                    onPressed: onPerdio,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                    child: const Text(
                      'PERDIÓ',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
              ],
            )
          ],
        ),
      ),
    );
  }

  Widget buildGrafica() {
    final List<FlSpot> spots = historialSaldo.isEmpty
        ? [FlSpot(0, saldoActual)]
        : historialSaldo
            .asMap()
            .entries
            .map((e) => FlSpot(e.key.toDouble(), e.value))
            .toList();

    final bool tendenciaAlcista =
        spots.length < 2 || spots.last.y >= spots.first.y;
    final Color colorTendencia =
        tendenciaAlcista ? Colors.greenAccent : Colors.redAccent;

    final LineChartBarData serieSaldo = LineChartBarData(
      spots: spots,
      isCurved: true,
      color: colorTendencia,
      barWidth: 3,
      dotData: FlDotData(
        show: true,
        getDotPainter: (spot, percent, barData, index) => FlDotCirclePainter(
          radius: 3.5,
          color: colorTendencia,
          strokeWidth: 1.5,
          strokeColor: Colors.white,
        ),
      ),
      belowBarData: BarAreaData(
        show: true,
        color: colorTendencia.withValues(alpha: 0.15),
      ),
    );

    final List<ShowingTooltipIndicators> tooltipIndicators = spots
        .map(
          (spot) => ShowingTooltipIndicators(
            [LineBarSpot(serieSaldo, 0, spot)],
          ),
        )
        .toList();

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          Expanded(
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.grey[900],
                borderRadius: BorderRadius.circular(12),
              ),
              child: LineChart(
                LineChartData(
                  minX: 0,
                  showingTooltipIndicators: tooltipIndicators,
                  titlesData: FlTitlesData(
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(showTitles: true, reservedSize: 44),
                    ),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 28,
                        interval: 1,
                      ),
                    ),
                    rightTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false),
                    ),
                    topTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false),
                    ),
                  ),
                  gridData: FlGridData(
                    show: true,
                    drawVerticalLine: true,
                    getDrawingHorizontalLine: (_) => FlLine(
                      color: Colors.white12,
                      strokeWidth: 1,
                    ),
                    getDrawingVerticalLine: (_) => FlLine(
                      color: Colors.white10,
                      strokeWidth: 1,
                    ),
                  ),
                  borderData: FlBorderData(
                    show: true,
                    border: Border.all(color: Colors.white24),
                  ),
                  lineTouchData: LineTouchData(
                    enabled: true,
                    handleBuiltInTouches: false,
                    touchTooltipData: LineTouchTooltipData(
                      getTooltipColor: (touchedSpot) => Colors.black87,
                      fitInsideHorizontally: true,
                      fitInsideVertically: true,
                      getTooltipItems: (touchedSpots) => touchedSpots
                          .map(
                            (spot) => LineTooltipItem(
                              '\$${spot.y.toStringAsFixed(2)}',
                              const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: 12,
                              ),
                            ),
                          )
                          .toList(),
                    ),
                  ),
                  lineBarsData: [serieSaldo],
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(
            'Puntos guardados: ${historialSaldo.length}',
            style: const TextStyle(fontSize: 14),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: () {
                setState(() {
                  historialSaldo = [saldoActual];
                });
              },
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
              child: const Text('🔄 Resetear gráfica'),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Calculadora de Binarias'),
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Calculadora'),
              Tab(text: 'Gráfica'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            buildCalculadora(),
            buildGrafica(),
          ],
        ),
      ),
    );
  }
}
