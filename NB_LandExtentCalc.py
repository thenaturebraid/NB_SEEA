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
                       QgsProcessingParameterFileDestination,
                       edit)
from qgis import processing
import os
import numpy as np
import csv
import itertools

class CalcLandExtentCalc(QgsProcessingAlgorithm):

    LC_OPENING_SHP = 'LC_OPENING_SHP'
    LC_OPENING = 'LC_OPENING'
    LC_CLOSING_SHP = 'LC_CLOSING_SHP'
    LC_CLOSING = 'LC_CLOSING'
    LC_NAME = 'LC_NAME'
    OUTPUT_CSV = 'OUTPUT_CSV'
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
            self.LC_OPENING_SHP
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
            self.OUTPUT_CSV,
            self.tr('Land cover/extent transition matrix'),
            'CSV files (*.csv)'
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
        OUTPUT_CSV = self.parameterAsFileOutput(parameters, self.OUTPUT_CSV, context)
        OUTPUT_LC = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)        
        
        # Intermediate files
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), 'accounts')
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)
        joinedLC = os.path.join(tempFolder, 'joinedLC.shp')
        joinedLCCSV = os.path.join(tempFolder, 'joinedLC.csv')
        intersectLC = os.path.join(tempFolder, 'intersectLC.shp')
        intersectCSV = os.path.join(tempFolder, 'intersectLandCover.csv')

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

        model_feedback.pushInfo('Intersecting opening and closing land cover...')
        # Intersect clean LCs
        alg_params = {
            'INPUT': LC_OPENING_SHP,
            'OVERLAY': LC_CLOSING_SHP,
            'OUTPUT': intersectLC}

        outputs['intersectLC'] = processing.run(
            'native:intersection',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        model_feedback.pushInfo('Calculating areas of opening and closing extents...')
        # Make a new field for area in opening LC
        if caps & QgsVectorDataProvider.AddAttributes:
            res = LC_OPENING_SHP.dataProvider().addAttributes([QgsField('area1_km2', QVariant.Double)])
            LC_OPENING_SHP.updateFields()

        # Calculate area for opening LC
        expContext = QgsExpressionContext()
        expContext.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(LC_OPENING_SHP))
        exp1 = QgsExpression('area($geometry) / 1000000')
        
        with edit(LC_OPENING_SHP):
            for f in LC_OPENING_SHP.getFeatures():
                expContext.setFeature(f)
                f['area1_km2'] = exp1.evaluate(expContext)
                LC_OPENING_SHP.updateFeature(f)

        # Make a new field for area for closing LC
        if caps & QgsVectorDataProvider.AddAttributes:
            res = LC_CLOSING_SHP.dataProvider().addAttributes([QgsField('area2_km2', QVariant.Double)])
            LC_CLOSING_SHP.updateFields()

        # Calculate area for closing LC
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

        ####################################
        ### Land cover transition matrix ###
        ####################################

        # Calculate area in intersected LC
        interLCFile = QgsVectorLayer(intersectLC)

        # Make a new field for area for closing LC
        if caps & QgsVectorDataProvider.AddAttributes:
            res = interLCFile.dataProvider().addAttributes([QgsField('area_km2', QVariant.Double)])
            interLCFile.updateFields()

        # Calculate area for closing LC
        expContext = QgsExpressionContext()
        expContext.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(interLCFile))
        exp1 = QgsExpression('area($geometry) / 1000000')
        
        with edit(interLCFile):
            for f in interLCFile.getFeatures():
                expContext.setFeature(f)
                f['area_km2'] = exp1.evaluate(expContext)
                interLCFile.updateFeature(f)

        # Write intersection LC attribute table to file
        features = interLCFile.getFeatures()
        fieldnames = [field.name() for field in interLCFile.fields()]
        
        with open(intersectCSV,'w', newline='') as output_file:
            line = ','.join(name for name in fieldnames) + '\n'
            output_file.write(line)

            for current, f in enumerate(features):
                if feedback.isCanceled():
                    break

                line = ','.join(str(f[name]) for name in fieldnames) + '\n'
                output_file.write(line)

        ############################
        ### Pivot table creation ###
        ############################

        hasHeaderRow = True
        header = []
        csvData = []

        with open(intersectCSV, "r") as f:
            reader = csv.reader(f, delimiter=',')
            for row in reader:
                if hasHeaderRow and reader.line_num == 1:
                    header.append(row)
                    continue # Ignore header row
                csvData.append(row)

        f.close()

        # Get header
        headerRow = header[0]

        # LC code and name dictionary
        LCnames = {}

        # LC changes [opening, closing, value]
        LCchanges = []

        for x in range(0, len(csvData)):
            row = csvData[x]

            # Get data
            lcOpening = row[headerRow.index(LC_OPENING)]
            lcName = row[headerRow.index(LC_NAME)]
            lcClosing = row[headerRow.index(LC_CLOSING)]
            area = row[headerRow.index('area_km2')]

            # Add lc code and name to dictionary
            lcPair = {lcOpening: lcName}
            LCnames.update(lcPair)

            # Add land cover information
            lcInfo = []
            lcInfo.append(lcOpening)
            lcInfo.append(lcClosing)
            lcInfo.append(area)

            LCchanges.append(lcInfo)

        LCnumpy = np.array(LCchanges)
        uniqueOpen = np.unique(np.array(LCnumpy[:,0]))
        uniqueClose = np.unique(np.array(LCnumpy[:,1]))
        combos = list(itertools.product(uniqueOpen, uniqueClose))

        # Produces a dictionary
        # Key: (x, y) where x is the LC at open and y is LC at close
        # Value: area of that combination
        changeDict = dict(zip(map(tuple, LCnumpy[:,[0,1]]), LCnumpy[:,[2]].ravel().tolist()))

        # Define arrays for the new CSV
        newHeader = [] # closing LC
        newColumn = [] # opening LC
        newCSV = []

        # Loop through the keys in LCnames and get them
        for key in LCnames:
            newHeader.append(key)
            newColumn.append(key)

        # Loop through each land cover in the first column (opening LC)
        for i in range(0, len(newColumn)):

            # Initialise an empty row first
            row = ['' for x in range(len(newColumn))]

            # Get the code for the opening cover
            openCover = newColumn[i]

            # Loop through the dictionary
            for key in changeDict:
                openCov = key[0]
                closeCov = key[1]
                areaChange = changeDict.get(key,'')

                # If the opening cover in the dictionary
                # is the cover we are currently analysing
                if str(openCov) == str(openCover):
                    j = newHeader.index(str(closeCov))
                    if str(openCov) == str(closeCov):
                        row[j] = '' # no change between years
                    else: # diff LC in open and close
                        row[j] = areaChange
            newCSV.append(row)

        # Replace the codes with the actual names
        namesHeader = ['Change from opening yr (column) to closing yr (row)']
        namesColumn = []
        outCSV = []

        for i in range(0, len(newColumn)):
            openName = LCnames.get(str(newColumn[i]))
            namesColumn.append(openName)

        for i in range(0, len(newHeader)):    
            closeName = LCnames.get(str(newHeader[i]))
            namesHeader.append(closeName)

        outCSV.append(namesHeader)

        for j in range(0, len(namesColumn)):
            row = newCSV[j]
            row.insert(0, namesColumn[j])
            outCSV.append(row)

        # Write the CSV
        with open(OUTPUT_CSV, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file, delimiter=',')
            writer.writerows(outCSV)

        csv_file.close()

        results[self.OUTPUT] = OUTPUT_LC
        results[self.OUTPUT_CSV] = OUTPUT_CSV
        
        return {self.OUTPUT: OUTPUT_LC,
                self.OUTPUT_CSV: OUTPUT_CSV}
