# -*- coding: utf-8 -*-



from qgis.PyQt.QtCore import (QCoreApplication, QVariant)
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingMultiStepFeedback,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingUtils,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingException)
from qgis import processing
import os
import numpy as np
import csv
import itertools

class rasterLandExtentCalc(QgsProcessingAlgorithm):

    LC_OPENING_RAS = 'LC_OPENING_RAS'
    LC_CLOSING_RAS = 'LC_CLOSING_RAS'
    LC_TABLE = 'LC_TABLE'
    LC_FIELD = 'LC_FIELD'
    LC_NAME = 'LC_NAME'
    OUTPUT = 'OUTPUT_CSV'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return rasterLandExtentCalc()

    def name(self):
        return 'rasterLandExtentCalc'

    def displayName(self):
        return self.tr('Calculate land extent accounts from raster datasets')

    def group(self):
        return self.tr('Nature Braid for SEEA')

    def groupId(self):
        return 'NBScripts'

    def shortHelpString(self):
        msg = '<p>This tool calculates land extent accounts from two raster datasets and returns the table output as a .CSV file.</p>'
        return self.tr(msg)

    def shortDescription(self):
        desc = "Calculate land extent accounts using two raster datasets"
        return self.tr(desc)

    def initAlgorithm(self, config=None):
        
        self.addParameter(
            QgsProcessingParameterRasterLayer(
            self.LC_OPENING_RAS,
            self.tr('Opening land cover raster')
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
            self.LC_CLOSING_RAS,
            self.tr('Closing land cover raster')
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.LC_TABLE,
            self.tr('Land cover table')
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_FIELD,
            self.tr('Linking field in land cover table'),
            '',
            self.LC_TABLE
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_NAME,
            self.tr('Field in land cover table with land cover labels'),
            '',
            self.LC_TABLE
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
            self.OUTPUT,
            self.tr('Land cover/extent table'),
            'CSV files (*.csv)'
            )
        )

    def processAlgorithm(self, parameters, context, model_feedback):
        # Final inputs and outputs
        LC_OPENING_RAS = self.parameterAsRasterLayer(parameters, self.LC_OPENING_RAS, context)
        LC_CLOSING_RAS = self.parameterAsRasterLayer(parameters, self.LC_CLOSING_RAS, context)
        LC_TABLE = self.parameterAsString(parameters, self.LC_TABLE, context)
        LC_FIELD = self.parameterAsString(parameters, self.LC_FIELD, context)
        LC_NAME = self.parameterAsString(parameters, self.LC_NAME, context)
        OUTPUT_CSV = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        # Intermediate files
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), 'accounts')
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)

        openingCount = os.path.join(tempFolder, 'openingCount.csv')
        closingCount = os.path.join(tempFolder, 'closingCount.csv')
        joinTable = os.path.join(tempFolder, 'joinTable.csv')

        feedback = QgsProcessingMultiStepFeedback(2, model_feedback)
        results = {}
        outputs = {}

        model_feedback.pushInfo('Checking opening land cover...')
        
        # Check the CRS of the opening land cover
        openUnits = LC_OPENING_RAS.crs().mapUnits()
        if openUnits != 0: # if not metres
            raise QgsProcessingException(self.tr("Opening dataset map units must be in meters"))

        # Check cell size of opening LC
        openCell = LC_OPENING_RAS.rasterUnitsPerPixelX()

        # Check the CRS of the closing land cover
        closeUnits = LC_CLOSING_RAS.crs().mapUnits()
        if closeUnits != 0: # if not metres
            raise QgsProcessingException(self.tr("Closing dataset map units must be in meters"))

        # Check cell size of closing LC
        closeCell = LC_CLOSING_RAS.rasterUnitsPerPixelX()

        # Get unique values report for opening
        alg_params = {
            'INPUT': LC_OPENING_RAS,
            'BAND': 1,
            'OUTPUT_TABLE': openingCount
        }

        outputs['openTable'] = processing.run(
            'native:rasterlayeruniquevaluesreport',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        step = 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        # Get unique values report for closing
        alg_params = {
            'INPUT': LC_CLOSING_RAS,
            'BAND': 1,
            'OUTPUT_TABLE': closingCount
        }

        outputs['closeTable'] = processing.run(
            'native:rasterlayeruniquevaluesreport',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        step += 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        # Read in CSV data from opening
        hasHeaderRow = True
        headerOpen = []
        csvOpen = []

        with open(openingCount, "r", encoding="utf8", errors="ignore") as f:
            reader = csv.reader(f, delimiter=',')
            for row in reader:
                if hasHeaderRow and reader.line_num == 1:
                    headerOpen.append(row)
                    continue # Ignore header row
                csvOpen.append(row)
        f.close()

        hasHeaderRow = True
        headerClose = []
        csvClose = []

        with open(closingCount, "r", encoding="utf8", errors="ignore") as f:
            reader = csv.reader(f, delimiter=',')
            for row in reader:
                if hasHeaderRow and reader.line_num == 1:
                    headerClose.append(row)
                    continue # Ignore header row
                csvClose.append(row)
        f.close()

        model_feedback.pushInfo('Counts of opening and closing land cover calculated')

        # Extract data from CSVs
        hasHeaderRow = True

        # Read in CSV data from land cover table
        headerTable = []
        csvTable = []

        with open(LC_TABLE, "r") as f:
            reader = csv.reader(f, delimiter=',')
            for row in reader:
                if hasHeaderRow and reader.line_num == 1:
                    headerTable.append(row)
                    continue # Ignore header row
                csvTable.append(row)
        f.close()

        # Construct dictionary of land cover labels
        lcDict = {}

        for i in range(0, len(csvTable)):
            row = csvTable[i]
            value = row[headerTable[0].index(LC_FIELD)]
            label = row[headerTable[0].index(LC_NAME)]

            lcDict[value] = label

        # Construct opening data dictionary
        dictOpen = {}
        landCodes = []

        for i in range(0, len(csvOpen)):
            row = csvOpen[i]

            # Get data
            lc = row[0]
            value = lc.split('.')[0]
            count = row[1]
            area_m2 = row[2]

            # Calculate area in km2
            area_km2 = float(area_m2) / 1000000.0

            # Add to dictionary
            dictOpen[value] = area_km2
            landCodes.append(value)

        # Construct closing data dictionary
        dictClose = {}

        for i in range(0, len(csvClose)):
            row = csvClose[i]

            # Get data
            lc = row[0]
            value = lc.split('.')[0]
            count = row[1]
            area_m2 = row[2]

            # Calculate area in km2
            area_km2 = float(area_m2) / 1000000.0

            # Add to dictionary
            dictClose[value] = area_km2

        # Constructed joinedCSV
        joinedCSV = []
        joinedHeader = ['CODE', 'Opening area (km2)', 'Closing area (km2)', 'Label', 'AbsDiff (km2)', 'RelDiff (%)']
        joinedCSV.append(joinedHeader)

        for x in range(0, len(landCodes)):
            openVal = round(dictOpen[landCodes[x]], 5)
            closeVal = round(dictClose[landCodes[x]], 5)
            label = lcDict[landCodes[x]].strip()

            # Calculate differences
            absDiff = float(closeVal) - float(openVal)
            relDiff = (float(absDiff) / float(openVal)) * 100.0

            lcInfo = [landCodes[x], openVal, closeVal, label, absDiff, relDiff]
            joinedCSV.append(lcInfo)

        # Write the CSV
        with open(OUTPUT_CSV, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file, delimiter=',')
            writer.writerows(joinedCSV)
     
        results[self.OUTPUT] = OUTPUT_CSV

        return results
