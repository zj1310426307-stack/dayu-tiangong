<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer><Name>road_open</Name><UserStyle><Name>road_open</Name><Title>广东主要道路中文标注</Title><FeatureTypeStyle>
    <Rule><LineSymbolizer><Stroke><CssParameter name="stroke">#F4D27A</CssParameter><CssParameter name="stroke-width">1.25</CssParameter><CssParameter name="stroke-opacity">0.88</CssParameter></Stroke></LineSymbolizer></Rule>
    <Rule><MaxScaleDenominator>250000</MaxScaleDenominator><TextSymbolizer><Label><ogc:PropertyName>name_zh</ogc:PropertyName></Label><Font><CssParameter name="font-family">Noto Sans CJK SC</CssParameter><CssParameter name="font-size">9</CssParameter></Font><LabelPlacement><LinePlacement/></LabelPlacement><Halo><Radius>1</Radius><Fill><CssParameter name="fill">#071923</CssParameter></Fill></Halo><Fill><CssParameter name="fill">#FFF0B8</CssParameter></Fill><VendorOption name="followLine">true</VendorOption><VendorOption name="conflictResolution">true</VendorOption></TextSymbolizer></Rule>
  </FeatureTypeStyle></UserStyle></NamedLayer>
</StyledLayerDescriptor>
