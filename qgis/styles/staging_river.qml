<?xml version="1.0" encoding="UTF-8"?>
<qgis version="3.44.0-Solothurn" styleCategories="Symbology|Labeling">
  <renderer-v2 type="categorizedSymbol" attr="quality_status" symbollevels="0" enableorderby="0">
    <categories>
      <category value="pending" label="待质检" symbol="0" render="true"/>
      <category value="passed" label="已通过" symbol="1" render="true"/>
      <category value="failed" label="未通过" symbol="2" render="true"/>
    </categories>
    <symbols>
      <symbol name="0" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="245,166,35,255"/><Option name="line_style" value="dash"/><Option name="line_width" value="0.9"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
      <symbol name="1" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="39,174,96,255"/><Option name="line_width" value="0.9"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
      <symbol name="2" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="220,53,69,255"/><Option name="line_style" value="dash"/><Option name="line_width" value="1.1"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple"><settings><text-style fieldName="coalesce(&quot;name&quot;,&quot;code&quot;)" isExpression="1" fontFamily="Noto Sans CJK SC" fontSize="9" namedStyle="Regular" textColor="45,55,72,255"/><placement placement="2" dist="1.5"/></settings></labeling>
</qgis>
