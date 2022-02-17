# -*- coding: utf-8 -*-



from qgis.PyQt.QtCore import (QCoreApplication, QVariant)
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingMultiStepFeedback,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingUtils,
                       QgsProcessingParameterField,
                       QgsProcessingParameterVectorDestination,
                       QgsVectorDataProvider,
                       QgsField,
                       QgsExpression,
                       QgsExpressionContext,
                       QgsExpressionContextUtils,
                       QgsVectorLayer,
                       edit)
from qgis import processing
import os

class CalcLandExtentCalc(QgsProcessingAlgorithm):

    LC_OPENING_SHP = 'LC_OPENING_SHP'
    LC_OPENING = 'LC_OPENING'
    LC_CLOSING_SHP = 'LC_CLOSING_SHP'
    LC_CLOSING = 'LC_CLOSING'
    LC_NAME = 'LC_NAME'
    OUTPUT = 'OUTPUT_LC'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CalcLandExtentCalc()

    def name(self):
        return 'CalcLandExtentCalc'

    def displayName(self):
        return self.tr('Calculate land extent accounts')

    def group(self):
        return self.tr('Nature Braid for SEEA')

    def groupId(self):
        return 'NBScripts'

    def shortHelpString(self):
        return self.tr("Calculate land extent accounts")

    def flags(self):
        return QgsProcessingAlgorithm.FlagHideFromToolbox

    def initAlgorithm(self, config=None):
        
        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.LC_OPENING_SHP,
            self.tr('Opening land cover (dissolve)'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_OPENING,
            self.tr('Opening year land extent field'),
            '',
            self.LC_OPENING_SHP
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.LC_CLOSING_SHP,
            self.tr('Closing land cover or extent dataset'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_CLOSING,
            self.tr('Closing year land extent field'),
            '',
            self.LC_CLOSING_SHP
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_NAME,
            self.tr('Field containing land cover class name'),
            '',
            self.LC_OPENING_SHP,
            optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterVectorDestination(
            self.OUTPUT,
            self.tr('Land accounts shapefile')
            )
        )
        
    def processAlgorithm(self, parameters, context, model_feedback):
        # Final inputs and outputs
        LC_OPENING_SHP = self.parameterAsVectorLayer(parameters, self.LC_OPENING_SHP, context)
        LC_OPENING = self.parameterAsString(parameters, self.LC_OPENING, context)
        LC_CLOSING_SHP = self.parameterAsVectorLayer(parameters, self.LC_CLOSING_SHP, context)
        LC_CLOSING = self.parameterAsString(parameters, self.LC_CLOSING, context)
        LC_NAME =  self.parameterAsString(parameters, self.LC_NAME, context)
        OUTPUT_LC = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)        
        
        # Intermediate files
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), 'accounts')
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)
        joinedLC = os.path.join(tempFolder, 'joinedLC.shp')
        joinedLCCSV = os.path.join(tempFolder, 'joinedLC.csv')

        feedback = QgsProcessingMultiStepFeedback(2, model_feedback)
        results = {}
        outputs = {}

        model_feedback.pushInfo('Checking opening land cover...')
        
        # Clean fields of everything except code and name
        fieldsToKeep = [str(LC_OPENING)]
        if str(LC_NAME) != '':
            fieldsToKeep.append(str(LC_NAME))
        allFields = [field.name() for field in LC_OPENING_SHP.fields()]
        fieldsToRemove = list(set(allFields) - set(fieldsToKeep))

        idxRemove = []
        for field in fieldsToRemove:
            idx = allFields.index(field)
            idxRemove.append(idx)

        caps = LC_OPENING_SHP.dataProvider().capabilities()

        # Clean opening LC of everything except code and name
        if caps & QgsVectorDataProvider.DeleteAttributes:
            res = LC_OPENING_SHP.dataProvider().deleteAttributes(idxRemove)
            LC_OPENING_SHP.updateFields()        

        # Make a new field for area
        if caps & QgsVectorDataProvider.AddAttributes:
            res = LC_OPENING_SHP.dataProvider().addAttributes([QgsField('area1_km2', QVariant.Double)])
            LC_OPENING_SHP.updateFields()

        # Calculate area
        expContext = QgsExpressionContext()
        expContext.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(LC_OPENING_SHP))
        exp1 = QgsExpression('area($geometry) / 1000000')
        
        with edit(LC_OPENING_SHP):
            for f in LC_OPENING_SHP.getFeatures():
                expContext.setFeature(f)
                f['area1_km2'] = exp1.evaluate(expContext)
                LC_OPENING_SHP.updateFeature(f)

        model_feedback.pushInfo('Checking closing land cover...')
        
        # Clean fields except for code
        fieldsToKeep = [str(LC_CLOSING)]
        allFields = [field.name() for field in LC_CLOSING_SHP.fields()]
        fieldsToRemove = list(set(allFields) - set(fieldsToKeep))

        idxRemove = []
        for field in fieldsToRemove:
            idx = allFields.index(field)
            idxRemove.append(idx)

        caps = LC_CLOSING_SHP.dataProvider().capabilities()
        if caps & QgsVectorDataProvider.DeleteAttributes:
            res = LC_CLOSING_SHP.dataProvider().deleteAttributes(idxRemove)
            LC_CLOSING_SHP.updateFields()
        
        # Make a new field for area
        if caps & QgsVectorDataProvider.AddAttributes:
            res = LC_CLOSING_SHP.dataProvider().addAttributes([QgsField('area2_km2', QVariant.Double)])
            LC_CLOSING_SHP.updateFields()

        expContext = QgsExpressionContext()
        expContext.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(LC_CLOSING_SHP))
        exp1 = QgsExpression('area($geometry) / 1000000')
        
        with edit(LC_CLOSING_SHP):
            for f in LC_CLOSING_SHP.getFeatures():
                expContext.setFeature(f)
                f['area2_km2'] = exp1.evaluate(expContext)
                LC_CLOSING_SHP.updateFeature(f)

        # Join the two land cover datasets
        alg_params = {
            'INPUT': LC_OPENING_SHP,
            'FIELD': LC_OPENING,
            'INPUT_2': LC_CLOSING_SHP,
            'FIELD_2': LC_CLOSING,
            'FIELDS_TO_COPY':[],
            'METHOD':1,
            'DISCARD_NONMATCHING':False,
            'PREFIX':'',
            'OUTPUT': OUTPUT_LC
        }

        outputs['joinLC'] = processing.run(
            'native:joinattributestable',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        joinedLCFile = QgsVectorLayer(OUTPUT_LC)

        fields = []
        for field in joinedLCFile.fields():
            fields.append(str(field.name()))

        caps = joinedLCFile.dataProvider().capabilities()

        # Make a new field for area
        if caps & QgsVectorDataProvider.AddAttributes:
            if 'AbsDiff' in fields:
                model_feedback.pushInfo('AbsDiff field present in soil shapefile')
                model_feedback.pushInfo('Deleting AbsDiff field...')
                idx = fields.index('AbsDiff')
                res = joinedLCFile.dataProvider().deleteAttributes([idx])

            if 'RelDiff' in fields:
                model_feedback.pushInfo('RelDiff field present in soil shapefile')
                model_feedback.pushInfo('Deleting RelDiff field...')
                idx = fields.index('RelDiff')
                res = joinedLCFile.dataProvider().deleteAttributes([idx])
                
            res = joinedLCFile.dataProvider().addAttributes([QgsField('AbsDiff', QVariant.Double), QgsField('RelDiff', QVariant.Double)])
            joinedLCFile.updateFields()

        with edit(joinedLCFile):
            for f in joinedLCFile.getFeatures():

                absDiff = float(f['area2_km2']) - float(f['area1_km2'])
                relDiff = (float(absDiff) / float(f['area1_km2'])) * 100.0
                
                f['AbsDiff'] = absDiff
                f['RelDiff'] = relDiff
                
                joinedLCFile.updateFeature(f)

        # Clean up the output file
        fieldsToKeep = [str(LC_OPENING), str(LC_CLOSING), 'area1_km2', 'area2_km2', 'AbsDiff', 'RelDiff']
        if str(LC_NAME) != '':
            fieldsToKeep.append(str(LC_NAME))
        allFields = [field.name() for field in joinedLCFile.fields()]
        fieldsToRemove = list(set(allFields) - set(fieldsToKeep))

        idxRemove = []
        for field in fieldsToRemove:
            idx = allFields.index(field)
            idxRemove.append(idx)

        caps = joinedLCFile.dataProvider().capabilities()
        if caps & QgsVectorDataProvider.DeleteAttributes:
            res = joinedLCFile.dataProvider().deleteAttributes(idxRemove)
            joinedLCFile.updateFields()

        results[self.OUTPUT] = OUTPUT_LC
        
        return results
